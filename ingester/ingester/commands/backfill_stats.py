"""backfill-stats: Pull historical Statcast and populate player_game_stats + pitcher_skill."""
from __future__ import annotations

import argparse
import sys

import psycopg
import requests

from ingester.db import get_connection, build_team_abbrev_map
from ingester.statcast import (
    SEASON_BOUNDARIES,
    _terminal_pa,
    agg_batter_game_stats,
    agg_pitcher_game_stats,
    agg_pitcher_vs_handedness,
    pull_statcast_chunks,
)

MLB_PEOPLE_URL = "https://statsapi.mlb.com/api/v1/sports/1/players"


# ---------------------------------------------------------------------------
# MLB Stats API: player fetch
# ---------------------------------------------------------------------------

def _fetch_players(season: int) -> list[dict]:
    resp = requests.get(
        MLB_PEOPLE_URL,
        params={"season": season, "gameType": "R"},
        timeout=30,
    )
    resp.raise_for_status()
    rows = []
    for p in resp.json().get("people", []):
        rows.append({
            "id":        p["id"],
            "full_name": p["fullName"],
            "team_id":   (p.get("currentTeam") or {}).get("id"),
            "position":  (p.get("primaryPosition") or {}).get("abbreviation"),
            "bats":      (p.get("batSide") or {}).get("code"),    # L/R/S
            "throws":    (p.get("pitchHand") or {}).get("code"),  # L/R
        })
    return rows


def _upsert_players(conn: psycopg.Connection, players: list[dict]) -> None:
    CHUNK = 500
    with conn.cursor() as cur:
        for i in range(0, len(players), CHUNK):
            cur.executemany(
                """
                INSERT INTO players (id, full_name, team_id, position, bats, throws, updated_at)
                VALUES (%(id)s, %(full_name)s, %(team_id)s, %(position)s, %(bats)s, %(throws)s, NOW())
                ON CONFLICT (id) DO UPDATE
                    SET full_name  = EXCLUDED.full_name,
                        team_id    = EXCLUDED.team_id,
                        position   = EXCLUDED.position,
                        bats       = EXCLUDED.bats,
                        throws     = EXCLUDED.throws,
                        updated_at = NOW()
                """,
                players[i : i + CHUNK],
            )


# ---------------------------------------------------------------------------
# player_game_stats upsert
# ---------------------------------------------------------------------------

_UPSERT_PGS = """
INSERT INTO player_game_stats (
    player_id, game_date, game_id, opponent_team_id, is_home,
    plate_appearances, at_bats, hits, home_runs, total_bases,
    strikeouts, walks, xwoba, woba,
    batters_faced, pitcher_strikeouts, hits_allowed, hr_allowed
)
VALUES (
    %(player_id)s, %(game_date)s, %(game_id)s, %(opponent_team_id)s, %(is_home)s,
    %(plate_appearances)s, %(at_bats)s, %(hits)s, %(home_runs)s, %(total_bases)s,
    %(strikeouts)s, %(walks)s, %(xwoba)s, %(woba)s,
    %(batters_faced)s, %(pitcher_strikeouts)s, %(hits_allowed)s, %(hr_allowed)s
)
ON CONFLICT (player_id, game_date, game_id) DO UPDATE
    SET opponent_team_id   = COALESCE(EXCLUDED.opponent_team_id,   player_game_stats.opponent_team_id),
        is_home            = EXCLUDED.is_home,
        plate_appearances  = COALESCE(EXCLUDED.plate_appearances,  player_game_stats.plate_appearances),
        at_bats            = COALESCE(EXCLUDED.at_bats,            player_game_stats.at_bats),
        hits               = COALESCE(EXCLUDED.hits,               player_game_stats.hits),
        home_runs          = COALESCE(EXCLUDED.home_runs,          player_game_stats.home_runs),
        total_bases        = COALESCE(EXCLUDED.total_bases,        player_game_stats.total_bases),
        strikeouts         = COALESCE(EXCLUDED.strikeouts,         player_game_stats.strikeouts),
        walks              = COALESCE(EXCLUDED.walks,              player_game_stats.walks),
        xwoba              = COALESCE(EXCLUDED.xwoba,              player_game_stats.xwoba),
        woba               = COALESCE(EXCLUDED.woba,               player_game_stats.woba),
        batters_faced      = COALESCE(EXCLUDED.batters_faced,      player_game_stats.batters_faced),
        pitcher_strikeouts = COALESCE(EXCLUDED.pitcher_strikeouts, player_game_stats.pitcher_strikeouts),
        hits_allowed       = COALESCE(EXCLUDED.hits_allowed,       player_game_stats.hits_allowed),
        hr_allowed         = COALESCE(EXCLUDED.hr_allowed,         player_game_stats.hr_allowed)
"""


def _ensure_players_exist(conn: psycopg.Connection, player_ids: set[int]) -> None:
    """Stub-insert any MLBAM IDs not yet in the players table to satisfy FK."""
    if not player_ids:
        return
    existing = {
        row[0]
        for row in conn.execute(
            "SELECT id FROM players WHERE id = ANY(%s)", (list(player_ids),)
        ).fetchall()
    }
    missing = player_ids - existing
    if missing:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO players (id, full_name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                [(pid, f"Unknown#{pid}") for pid in missing],
            )


def _upsert_game_stats(conn: psycopg.Connection, rows: list[dict]) -> None:
    if not rows:
        return
    CHUNK = 1000
    with conn.cursor() as cur:
        for i in range(0, len(rows), CHUNK):
            cur.executemany(_UPSERT_PGS, rows[i : i + CHUNK])


# ---------------------------------------------------------------------------
# pitcher_skill upsert (handedness splits)
# ---------------------------------------------------------------------------

_UPSERT_PS = """
INSERT INTO pitcher_skill (
    player_id, season, vs_handedness,
    batters_faced, woba_against, xwoba_against,
    k_rate, bb_rate, hr_per_pa, hits_per_pa, updated_at
)
VALUES (
    %(player_id)s, %(season)s, %(vs_handedness)s,
    %(batters_faced)s, %(woba_against)s, %(xwoba_against)s,
    %(k_rate)s, %(bb_rate)s, %(hr_per_pa)s, %(hits_per_pa)s, NOW()
)
ON CONFLICT (player_id, season, vs_handedness) DO UPDATE
    SET batters_faced  = EXCLUDED.batters_faced,
        woba_against   = EXCLUDED.woba_against,
        xwoba_against  = EXCLUDED.xwoba_against,
        k_rate         = EXCLUDED.k_rate,
        bb_rate        = EXCLUDED.bb_rate,
        hr_per_pa      = EXCLUDED.hr_per_pa,
        hits_per_pa    = EXCLUDED.hits_per_pa,
        updated_at     = NOW()
"""


def _upsert_pitcher_skill(
    conn: psycopg.Connection, rows: list[dict], season: int
) -> None:
    if not rows:
        return
    for r in rows:
        r["season"] = season
    CHUNK = 500
    with conn.cursor() as cur:
        for i in range(0, len(rows), CHUNK):
            cur.executemany(_UPSERT_PS, rows[i : i + CHUNK])


# ---------------------------------------------------------------------------
# Command entrypoint
# ---------------------------------------------------------------------------

def cmd_backfill_stats(args: argparse.Namespace) -> None:
    season: int = getattr(args, "season", 2025)

    if season not in SEASON_BOUNDARIES:
        sys.exit(
            f"[backfill-stats] Season {season} not in SEASON_BOUNDARIES. "
            f"Supported: {sorted(SEASON_BOUNDARIES)}"
        )

    conn = get_connection()

    # --- 1. Players --------------------------------------------------------
    print(f"[backfill-stats] Fetching {season} roster from MLB Stats API…")
    players = _fetch_players(season)
    print(f"  → {len(players)} players")
    _upsert_players(conn, players)
    conn.commit()
    print("  → Upserted into players table")

    # --- 2. Team abbreviation map ------------------------------------------
    abbrev_to_id = build_team_abbrev_map(conn)

    # --- 3. Statcast in weekly chunks -------------------------------------
    print(
        f"[backfill-stats] Pulling Statcast for {season} season\n"
        "  (subsequent runs read from pybaseball disk cache)…"
    )

    total_batter_rows = 0
    total_pitcher_rows = 0
    pa_chunks: list = []  # terminal-PA DataFrames for pitcher handedness agg

    for chunk_df in pull_statcast_chunks(season):
        batter_rows  = agg_batter_game_stats(chunk_df, abbrev_to_id)
        pitcher_rows = agg_pitcher_game_stats(chunk_df, abbrev_to_id)

        all_ids = {r["player_id"] for r in batter_rows + pitcher_rows}
        _ensure_players_exist(conn, all_ids)
        _upsert_game_stats(conn, batter_rows)
        _upsert_game_stats(conn, pitcher_rows)
        conn.commit()

        # Keep terminal-PA rows (lightweight) for pitcher handedness agg
        pa_chunks.append(_terminal_pa(chunk_df))

        total_batter_rows  += len(batter_rows)
        total_pitcher_rows += len(pitcher_rows)
        print(
            f"    chunk done — {len(batter_rows)} batter rows, "
            f"{len(pitcher_rows)} pitcher rows"
        )

    print(f"\n[backfill-stats] Statcast done.")
    print(f"  Total batter game rows : {total_batter_rows}")
    print(f"  Total pitcher game rows: {total_pitcher_rows}")

    # --- 4. Pitcher vs handedness → pitcher_skill -------------------------
    print("[backfill-stats] Computing pitcher_skill handedness splits…")
    ph_rows = agg_pitcher_vs_handedness(pa_chunks)
    print(f"  → {len(ph_rows)} (pitcher, handedness) pairs before min-BF filter")

    ph_rows = [r for r in ph_rows if r["batters_faced"] >= 50]
    print(f"  → {len(ph_rows)} after ≥50 BF filter")

    pitcher_ids = {r["player_id"] for r in ph_rows}
    _ensure_players_exist(conn, pitcher_ids)
    _upsert_pitcher_skill(conn, ph_rows, season)
    conn.commit()
    print("  → Upserted into pitcher_skill")

    conn.close()
    print("[backfill-stats] Done.")
