"""refresh-pitcher-priors: Marcel-style multi-year true-talent prior per pitcher (Lever 4).

Aggregates each pitcher's prior three seasons of allowed rates straight from the
Statcast cache (recency 5/4/3, BF-weighted, regressed to league) into
pitcher_projection_prior. compute_pitcher_skill_rows then regresses in-season
allowed rates toward THIS prior instead of the flat league mean (gated by
DIAMOND_PITCHER_PRIOR_ENABLED).

Sourced from Statcast (not player_game_stats like the batter prior) so it carries
BB-allowed and needs no multi-season game-log backfill. Priors are static within a
season, so this only runs when a new season's prior years are settled.

    uv run python main.py refresh-pitcher-priors --season 2026
"""
from __future__ import annotations

import argparse

from ingester.commands.refresh_skills import load_all_statcast_pa
from ingester.db import get_connection
from ingester.projection.constants import (
    LEAGUE_BB_PER_PA,
    LEAGUE_HIT_PER_PA,
    LEAGUE_HR_PER_PA,
    LEAGUE_K_PER_PA,
    MARCEL_SEASON_WEIGHTS,
)
from ingester.projection.pitcher_prior import (
    PitcherSeasonLine,
    compute_pitcher_marcel_prior,
)
from ingester.statcast import agg_pitcher_vs_handedness


def _season_lines(season: int) -> dict[int, PitcherSeasonLine]:
    """Per-pitcher counting totals for one season, pooled across batter handedness.

    Reconstructs counts from agg_pitcher_vs_handedness' per-(pitcher, hand) rates ×
    batters_faced, summed over both hands. Reads the Statcast disk cache.
    """
    rows = agg_pitcher_vs_handedness(load_all_statcast_pa(season))
    acc: dict[int, dict[str, float]] = {}
    for r in rows:
        bf = r["batters_faced"]
        if not bf:
            continue
        a = acc.setdefault(r["player_id"], {"bf": 0.0, "k": 0.0, "bb": 0.0, "hr": 0.0, "hits": 0.0})
        a["bf"] += bf
        a["k"] += (r["k_rate"] or 0.0) * bf
        a["bb"] += (r["bb_rate"] or 0.0) * bf
        a["hr"] += (r["hr_per_pa"] or 0.0) * bf
        a["hits"] += (r["hits_per_pa"] or 0.0) * bf
    return {
        pid: PitcherSeasonLine(
            bf=int(round(a["bf"])),
            k=int(round(a["k"])),
            bb=int(round(a["bb"])),
            hr=int(round(a["hr"])),
            hits=int(round(a["hits"])),
        )
        for pid, a in acc.items()
        if a["bf"] > 0
    }


def cmd_refresh_pitcher_priors(args: argparse.Namespace) -> None:
    target: int = getattr(args, "season", 2026)

    # Pull the three prior seasons once each (cache-backed). Skip a year whose pull
    # fails (older seasons can hit Baseball Savant error pages on a cold cache) —
    # the recency-weighted Marcel degrades gracefully to the seasons it does have.
    by_player: dict[int, dict[int, PitcherSeasonLine]] = {}
    loaded: list[int] = []
    for offset in range(1, len(MARCEL_SEASON_WEIGHTS) + 1):
        yr = target - offset
        print(f"[refresh-pitcher-priors] aggregating prior season {yr}…")
        try:
            lines = _season_lines(yr)
        except Exception as e:  # noqa: BLE001 — a flaky pull shouldn't sink the whole prior
            print(f"[refresh-pitcher-priors]   skipped {yr}: {str(e)[:80]}")
            continue
        for pid, line in lines.items():
            by_player.setdefault(pid, {})[yr] = line
        loaded.append(yr)
    if not loaded:
        print("[refresh-pitcher-priors] no prior seasons loadable — nothing written.")
        return

    conn = get_connection()
    known = {r[0] for r in conn.execute("SELECT id FROM players").fetchall()}

    rows: list[dict] = []
    for pid, seasons in by_player.items():
        if pid not in known:
            continue  # FK target must exist; only pitchers active now matter as priors
        prior = compute_pitcher_marcel_prior(
            seasons,
            target,
            league_k_rate=LEAGUE_K_PER_PA,
            league_bb_rate=LEAGUE_BB_PER_PA,
            league_hr_per_pa=LEAGUE_HR_PER_PA,
            league_hits_per_pa=LEAGUE_HIT_PER_PA,
        )
        if prior is None:
            continue
        rows.append({
            "player_id": pid,
            "season": target,
            "proj_k_rate": prior.k_rate,
            "proj_bb_rate": prior.bb_rate,
            "proj_hr_per_pa": prior.hr_per_pa,
            "proj_hits_per_pa": prior.hits_per_pa,
            "proj_bf": prior.proj_bf,
        })

    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                """
                INSERT INTO pitcher_projection_prior (
                    player_id, season, proj_k_rate, proj_bb_rate,
                    proj_hr_per_pa, proj_hits_per_pa, proj_bf, method, updated_at
                )
                VALUES (
                    %(player_id)s, %(season)s, %(proj_k_rate)s, %(proj_bb_rate)s,
                    %(proj_hr_per_pa)s, %(proj_hits_per_pa)s, %(proj_bf)s, 'marcel', NOW()
                )
                ON CONFLICT (player_id, season, method) DO UPDATE
                    SET proj_k_rate      = EXCLUDED.proj_k_rate,
                        proj_bb_rate     = EXCLUDED.proj_bb_rate,
                        proj_hr_per_pa   = EXCLUDED.proj_hr_per_pa,
                        proj_hits_per_pa = EXCLUDED.proj_hits_per_pa,
                        proj_bf          = EXCLUDED.proj_bf,
                        updated_at       = NOW()
                """,
                row,
            )
    conn.commit()
    conn.close()
    print(
        f"[refresh-pitcher-priors] Wrote {len(rows)} pitcher priors for {target} "
        f"(Marcel {MARCEL_SEASON_WEIGHTS}, Statcast-sourced from {loaded})."
    )
