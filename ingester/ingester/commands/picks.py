"""record-picks / score-picks: select, lock, and grade the daily Model's Picks.

This module is the SINGLE owner of the picks bar: the web board renders the
recorded rows from GET /api/model-picks (it no longer computes its own picks),
so every selection decision lives here.

Selection model (July 2026 rework — "fewer, stricter, locked"):
  · The whole slate is projected in the morning run (predicted lineups fill in
    for unconfirmed ones), so `record-picks` can lock up to MAX_PICKS picks at
    morning prices — early lines are where CLV is earned.
  · Hard slate budget: at most PICK_BUDGET rows are EVER recorded per slate
    (active or bumped, all count). If fewer qualify in the morning, later runs
    may fill the remainder — the bar, not the clock, gates. Zero-pick days are
    fine; too few beats too many.
  · A locked pick is never displaced by a "better" late play. The only thing
    that can move it is a LINEUP CHANGE: when a pick's game lineup posts or
    changes (detected by lineup_hash), the pick is re-checked at its locked
    price against the current model number; if it no longer clears, it is
    bumped (bump_reason='lineup') — still graded, still counted. Market moves
    never trigger re-evaluation by construction.

`score-picks` grades a prior slate against actuals the next morning (game
markets need final scores; props additionally need player_game_stats; a prop
whose player never appeared in a final game is VOID, like a book's DNP rule).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import date, datetime, timedelta, timezone

import requests

from ingester.db import eastern_today, get_connection
from ingester.projection.constants import DEAD_GAME_STATUSES, MODEL_VERSION

# ── the bar (single source of truth — the web renders recorded rows) ─────────
# Jul 2026 tightening, from the first 78 settled picks:
#   · MIN_EDGE 0.04 → 0.06 — cut the marginal tail; NOTE this makes MIN_EDGE ==
#     STRONG_EDGE, so `strong` now reduces to model_prob ≥ 0.5 (accepted:
#     Strong ≈ favorite-side value; the formula is deliberately unchanged).
#   · MAX_EDGE 0.15 → 0.125 — the [.125,.15] edge bucket went 19-19 while
#     [.10,.125) went 15-9; same lesson as the earlier 0.25 → 0.15 cut (the
#     0/3 day's misses were 18–21pt "edges"): past a point, model−market
#     disagreement is model error, not free money.
#   · 'hit' excluded — backtests show H≥1 has near-zero skill signal, so
#     model−market gaps there are mostly noise. HR (where the model has a
#     validated edge) and game markets stay.
#   · HR props must not contradict the hit-rate traffic light (season clear
#     rate, n≥15): no overs on red, no unders on green.
MIN_EDGE = 0.06
MAX_EDGE = 0.125
MIN_EV = 0.05
MIN_MODEL_PROB = 0.40
LONGSHOT_EDGE = 0.08
STRONG_EDGE = 0.06
MAX_PICKS = 3
# Hard per-slate budget: every model_picks row ever recorded for the slate counts
# (active, lineup-bumped, frozen — all of it). A lineup bump does NOT refund a row.
PICK_BUDGET = 3
# The Analyst gate (V64) debates the wider candidate set (one per game) before promotion, so a
# vetoed top pick can be replaced by the next-best and the veto annotates Best Lines.
CANDIDATE_LIMIT = 6
EXCLUDED_MARKETS = {"pitcher_k", "pitcher_outs", "hit"}
HIT_RATE_VETO_MIN_N = 15  # season sample needed before the traffic light can veto
# Per-market veto bands: (no OVER below, no UNDER above). Market-specific because
# clear-rate scales differ wildly — the hit bands applied to HR would veto every
# slugger alive (nobody homers in 45% of games). Markets absent here never veto.
HIT_RATE_VETO_BANDS: dict[str, tuple[float, float]] = {
    "hit": (0.45, 0.65),
    "hr": (0.08, 0.50),
}

# Resolved from the env so the dockerized nightly (where the API is the `api` compose
# service, not localhost) can reach it without daily.py threading an --api flag through.
# Mirrors the mcp-server's DIAMOND_API_URL. Local/host runs fall back to localhost. An
# explicit --api still wins (see cmd_record_picks).
DEFAULT_API = os.environ.get("DIAMOND_API_URL", "http://localhost:8080")
# Shared key for the server-to-server debate gate (POST /api/debate/pick). Blank => the gate is
# off and the board stays mechanical (graceful — the gate only ever demotes on an explicit pass).
INTERNAL_KEY = os.environ.get("AGENT_INTERNAL_KEY", "")


def _get_json(url: str) -> object:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _sim_totals_veto(play: dict, sim: dict | None) -> bool:
    """A totals lean is vetoed when the Monte-Carlo sim lands on the other side."""
    if play["market"] != "total" or play.get("line") is None or not sim:
        return False
    t = next((x for x in sim.get("totals", []) if x["gameId"] == play["gameId"]), None)
    if t is None:
        return False
    if play["side"] == "over":
        return not (t["simTotal"] > play["line"])
    return not (t["simTotal"] < play["line"])


def _sim_corroborates(play: dict, sim: dict | None) -> bool:
    """Sim agreement (totals side, or prop player on the sim leaderboard) nudges score."""
    if not sim:
        return False
    if play["market"] == "total" and play.get("line") is not None:
        t = next((x for x in sim.get("totals", []) if x["gameId"] == play["gameId"]), None)
        if t is None:
            return False
        return t["simTotal"] > play["line"] if play["side"] == "over" else t["simTotal"] < play["line"]
    if play.get("playerId") is not None and play["side"] == "over":
        key = {"hit": "hits", "hr": "homeRuns"}.get(play["market"])
        if key is None:
            return False
        return any(r["playerId"] == play["playerId"] for r in sim.get("props", {}).get(key, []))
    return False


def _hit_rate_veto(play: dict, hit_rates: dict | None) -> bool:
    """Veto a prop that contradicts the player's season clear rate (traffic light).

    Per-market bands (HIT_RATE_VETO_BANDS): an OVER on a player below the market's
    floor, or an UNDER on one above its ceiling, needs more than a model-market gap
    to justify. No band for the market, or no data → no veto.
    """
    if not hit_rates or play.get("playerId") is None:
        return False
    band = HIT_RATE_VETO_BANDS.get(play["market"])
    if band is None:
        return False
    hr = hit_rates.get(f"{play['playerId']}:{play['market']}")
    if hr is None or hr.get("season") is None or hr.get("nSeason", 0) < HIT_RATE_VETO_MIN_N:
        return False
    over_floor, under_ceiling = band
    if play["side"] == "over":
        return hr["season"] < over_floor
    if play["side"] == "under":
        return hr["season"] > under_ceiling
    return False


def _scored_candidates(plays: list[dict], sim: dict | None,
                       hit_rates: dict | None) -> list[tuple[float, dict, float, bool]]:
    """Apply the Model's Picks bar + vetoes; return (score, play, edge, strong) sorted best-first."""
    candidates: list[tuple[float, dict, float, bool]] = []
    for p in plays:
        if p["market"] in EXCLUDED_MARKETS or p.get("fairProb") is None:
            continue
        edge = p["modelProb"] - p["fairProb"]
        if edge < MIN_EDGE or edge > MAX_EDGE:
            continue
        if p["evPct"] < MIN_EV:
            continue
        if p["modelProb"] < MIN_MODEL_PROB and edge < LONGSHOT_EDGE:
            continue
        if _sim_totals_veto(p, sim):
            continue
        if _hit_rate_veto(p, hit_rates):
            continue
        corroborated = _sim_corroborates(p, sim)
        score = edge + 0.5 * p["evPct"] + (0.02 if corroborated else 0.0)
        strong = edge >= STRONG_EDGE and p["modelProb"] >= 0.5
        candidates.append((score, p, edge, strong))
    candidates.sort(key=lambda c: -c[0])
    return candidates


def _take_one_per_game(candidates: list[tuple[float, dict, float, bool]], cap: int) -> list[dict]:
    """At most one pick per game, in board order, up to `cap`."""
    picks: list[dict] = []
    used_games: set[int] = set()
    for _score, p, edge, strong in candidates:
        if p["gameId"] in used_games:
            continue
        used_games.add(p["gameId"])
        picks.append({**p, "edge": edge, "strong": strong})
        if len(picks) == cap:
            break
    return picks


def build_picks(plays: list[dict], sim: dict | None,
                hit_rates: dict | None = None) -> list[dict]:
    """Apply the Model's Picks bar; returns at most MAX_PICKS plays, board order."""
    return _take_one_per_game(_scored_candidates(plays, sim, hit_rates), MAX_PICKS)


def build_candidates(plays: list[dict], sim: dict | None, hit_rates: dict | None = None,
                     limit: int = CANDIDATE_LIMIT) -> list[dict]:
    """The wider candidate set (one per game) the Analyst gate debates before promotion."""
    return _take_one_per_game(_scored_candidates(plays, sim, hit_rates), limit)


def _active_slate(api: str) -> date:
    """The slate users are currently shown (server resolves lineup+projection readiness)."""
    return date.fromisoformat(_get_json(f"{api}/api/slate/active")["date"])


def _pick_key(p: dict) -> tuple:
    """Stable identity for a pick: one per selection per slate. line is excluded so a
    line move keeps the first-shown pick; player_id is None for game markets."""
    return (p["gameId"], p["market"], p["side"], p.get("playerId"))


# Sentinels for _current_model_prob: the pick's player is OUT of the (re)projected
# lineup, or the model number is UNKNOWN this tick (no projection yet — retry later).
OUT = "OUT"
UNKNOWN = "UNKNOWN"

# Mirror of OddsService.PROB_EPS: a model prob this close to 0/1 is a degenerate
# projection, not a confident number — treat it as UNKNOWN.
PROB_EPS = 1e-6

# Poisson grid bound, mirror of OddsModel.MAX_RUNS.
_MAX_RUNS = 30


def american_to_decimal(american: int) -> float:
    """American → decimal odds. +150 → 2.50, −120 → 1.833."""
    return 1.0 + american / 100.0 if american > 0 else 1.0 + 100.0 / -american


def _poisson_pmf(lam: float, max_runs: int = _MAX_RUNS) -> list[float]:
    """PMF over 0..max_runs via the recurrence p_k = p_{k-1}·λ/k (mirror of OddsModel)."""
    p = [math.exp(-lam)]
    for k in range(1, max_runs + 1):
        p.append(p[-1] * lam / k)
    return p


def poisson_game_prob(market: str, side: str, line: float | None,
                      exp_home: float, exp_away: float) -> float | None:
    """Model probability for a game-market side from projected team runs.

    Exact mirror of OddsModel + OddsService.gameModelProb (independent Poissons on a
    bounded grid; moneyline ties split 50/50; run_line `line` is the chosen side's
    signed spread). Used only as the re-eval fallback when a locked pick has dropped
    off /api/odds/best — parity with the Java model keeps re-checks consistent with
    the number the pick was taken at.
    """
    ph = _poisson_pmf(exp_home)
    pa = _poisson_pmf(exp_away)
    if market == "moneyline":
        win = sum(ph[h] * pa[a] for h in range(len(ph)) for a in range(len(pa)) if h > a)
        tie = sum(ph[r] * pa[r] for r in range(len(ph)))
        p_home = win + 0.5 * tie
        return p_home if side == "home" else 1.0 - p_home
    if line is None:
        return None
    if market == "total":
        over = sum(ph[h] * pa[a]
                   for h in range(len(ph)) for a in range(len(pa)) if h + a > line)
        return over if side == "over" else 1.0 - over
    if market == "run_line":
        if side == "home":
            return sum(ph[h] * pa[a]
                       for h in range(len(ph)) for a in range(len(pa)) if h - a > -line)
        return sum(ph[h] * pa[a]
                   for h in range(len(ph)) for a in range(len(pa)) if a - h > -line)
    return None


def _sane(p: float | None) -> float | None:
    """Degenerate probabilities (see PROB_EPS) are no probability at all."""
    if p is None or p <= PROB_EPS or p >= 1.0 - PROB_EPS:
        return None
    return p


def _lineup_hash(conn, game_id: int) -> str:
    """Fingerprint of the game's posted lineups: md5 over both sides' ordered player
    ids ("h:pid,pid,...|a:pid,pid,..."), a missing side hashing as an empty segment.
    Stored on each pick at lock time; a later mismatch IS the lineup-change signal
    (game_lineups is DELETE+INSERTed on re-post and confirmed_at COALESCEs, so there
    is no other change marker). Market moves never touch it — by construction the
    only re-eval trigger is a lineup event.
    """
    rows = conn.execute(
        """
        SELECT is_home, player_id FROM game_lineups
        WHERE game_id = %s
        ORDER BY is_home DESC, batting_order
        """,
        (game_id,),
    ).fetchall()
    home = ",".join(str(int(pid)) for is_home, pid in rows if is_home)
    away = ",".join(str(int(pid)) for is_home, pid in rows if not is_home)
    return hashlib.md5(f"h:{home}|a:{away}".encode()).hexdigest()


def _current_model_prob(conn, plays: list[dict], pick: dict) -> float | str:
    """The model's CURRENT probability for a locked pick's exact selection.

    Tries the already-fetched /api/odds/best plays first (same game/market/side/player
    AND the locked line — a moved line prices a different event), then falls back to
    the projection tables directly (the pick may have dropped off the priced board).
    Returns OUT when a prop's player is absent from the re-projected lineup (the
    scratch case) and UNKNOWN when no usable model number exists this tick.
    """
    for p in plays:
        if (p["gameId"] == pick["game_id"] and p["market"] == pick["market"]
                and p["side"] == pick["side"]
                and p.get("playerId") == pick["player_id"]
                and _same_line(p.get("line"), pick["line"])):
            prob = _sane(p.get("modelProb"))
            if prob is not None:
                return prob
    if pick["market"] in ("hit", "hr"):
        col = "p_hr" if pick["market"] == "hr" else "p_hit_1plus"
        row = conn.execute(
            f"SELECT {col} FROM batter_projections WHERE game_id = %s AND player_id = %s",
            (pick["game_id"], pick["player_id"]),
        ).fetchone()
        if row is None:
            return OUT  # not in the (re)projected lineup — the scratch case
        prob = _sane(float(row[0]) if row[0] is not None else None)
        return prob if prob is not None else UNKNOWN
    row = conn.execute(
        "SELECT expected_home_runs, expected_away_runs FROM game_projections "
        "WHERE game_id = %s",
        (pick["game_id"],),
    ).fetchone()
    if row is None or row[0] is None or row[1] is None:
        return UNKNOWN
    prob = _sane(poisson_game_prob(
        pick["market"], pick["side"],
        float(pick["line"]) if pick["line"] is not None else None,
        float(row[0]), float(row[1]),
    ))
    return prob if prob is not None else UNKNOWN


def _same_line(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return float(a) == float(b)


def bar_recheck(model_prob_now: float, locked_fair_prob: float,
                locked_price_decimal: float) -> bool:
    """Does the pick still clear the bar at its LOCKED terms, given the model's
    current number? Floors only — no MAX_EDGE ceiling (a model move further in our
    favor must never bump a locked pick) — and only the locked fair prob / price are
    used, so current market prices cannot enter the decision.
    """
    edge = model_prob_now - locked_fair_prob
    ev = model_prob_now * locked_price_decimal - 1.0
    if edge < MIN_EDGE or ev < MIN_EV:
        return False
    return model_prob_now >= MIN_MODEL_PROB or edge >= LONGSHOT_EDGE


def plan_lineup_reeval(rows: list[dict], now: datetime) -> list[tuple]:
    """Re-evaluate locked picks whose game lineup changed. Pure (no DB/IO).

    Each row: pick_id, active, bump_reason, start_time, stored_hash, current_hash,
    model_prob_now (float | OUT | UNKNOWN), locked_fair_prob, locked_price_decimal.
    Ops, in apply order:
      · ("lineup_bump",  pick_id, current_hash) — active pick no longer clears (or
        its player is OUT): off the board, bump_reason='lineup', still graded.
      · ("refresh_hash", pick_id, current_hash) — lineup changed but the pick still
        clears (or a lineup-bumped row still fails): just note the new lineup.
      · ("unbump",       pick_id, current_hash) — a lineup-bumped row whose lineup
        changed AGAIN and now clears at its locked terms returns to the board
        (budget-free: its row was already counted) while active slots allow.
    Started games are frozen; unchanged hashes are no-ops; UNKNOWN model numbers are
    skipped WITHOUT refreshing the hash so the next tick retries the re-check.
    """
    ops: list[tuple] = []
    active_count = sum(1 for r in rows if r["active"])

    def _clears(r) -> bool | None:
        mp = r["model_prob_now"]
        if mp == UNKNOWN or mp is None:
            return None
        if mp == OUT:
            return False
        return bar_recheck(mp, r["locked_fair_prob"], r["locked_price_decimal"])

    changed = [
        r for r in rows
        if r["current_hash"] != r["stored_hash"]
        and not (r["start_time"] is not None and r["start_time"] <= now)
    ]
    for r in (r for r in changed if r["active"]):
        clears = _clears(r)
        if clears is None:
            continue
        if clears:
            ops.append(("refresh_hash", r["pick_id"], r["current_hash"]))
        else:
            ops.append(("lineup_bump", r["pick_id"], r["current_hash"]))
            active_count -= 1
    for r in (r for r in changed if not r["active"] and r["bump_reason"] == "lineup"):
        clears = _clears(r)
        if clears is None:
            continue
        if clears and active_count < MAX_PICKS:
            ops.append(("unbump", r["pick_id"], r["current_hash"]))
            active_count += 1
        else:
            ops.append(("refresh_hash", r["pick_id"], r["current_hash"]))
    return ops


def plan_reconcile(picks: list[dict], existing: dict, now: datetime,
                   board_loaded: bool, budget: int) -> list[tuple]:
    """Decide which of today's qualifying picks get recorded. Pure (no DB/IO).

    ``existing`` maps a pick key (see _pick_key) to (pick_id, active, start_time,
    bump_reason); ``budget`` is the slate's remaining row allowance
    (PICK_BUDGET − rows ever recorded). Returns ops in apply order:
      · ("insert", rank, pick) — newly qualifies and budget remains; locked at
        first-shown price. Ranks are assigned once, at insert, and never rewritten.
      · ("keep", pick_id)      — TRANSITION ONLY: re-promote a legacy 'displaced'
        row (pre-budget-regime churn) that re-qualified, at its original rank.
    There is NO displacement: an active locked pick absent from today's candidates
    is left untouched — that's the lock. Lineup-bumped rows only return via
    plan_lineup_reeval's unbump. When the board didn't load (odds expired mid-slate),
    nothing happens — an empty pull must never mutate legitimately-recorded picks.
    """
    if not board_loaded:
        return []
    ops: list[tuple] = []
    active_count = sum(1 for (_id, active, _start, _reason) in existing.values() if active)
    inserts = 0
    for p in picks:
        key = _pick_key(p)
        if key in existing:
            pick_id, active, start, bump_reason = existing[key]
            if (not active and bump_reason == "displaced"
                    and not (start is not None and start <= now)
                    and active_count < MAX_PICKS):
                ops.append(("keep", pick_id))
                active_count += 1
            continue  # active (locked, no-op) or lineup-bumped (re-eval only)
        if inserts < budget and active_count < MAX_PICKS:
            ops.append(("insert", len(existing) + inserts + 1, p))
            inserts += 1
            active_count += 1
    return ops


# ── the Analyst promotion gate (V64) ─────────────────────────────────────────

def _cached_verdict(conn, slate, cand: dict) -> str | None:
    """A selection is debated once per slate; reuse the cached verdict if present."""
    row = conn.execute(
        "SELECT verdict FROM pick_verdicts WHERE slate_date=%s AND game_id=%s "
        "AND market=%s AND side=%s AND player_id IS NOT DISTINCT FROM %s",
        (slate, cand["gameId"], cand["market"], cand["side"], cand.get("playerId")),
    ).fetchone()
    return row[0] if row else None


def _debate_and_store(conn, api: str, slate, cand: dict) -> str | None:
    """Debate a candidate via the server gate and persist the verdict. Returns the verdict, or
    None on any failure (gate off / AI disabled / error) so the candidate promotes mechanically —
    the gate is additive and must never break record-picks."""
    if not INTERNAL_KEY:
        return None
    try:
        resp = requests.post(
            f"{api}/api/debate/pick",
            headers={"X-Internal-Key": INTERNAL_KEY},
            json={
                "gameId": cand["gameId"], "market": cand["market"], "side": cand["side"],
                "line": cand.get("line"), "playerId": cand.get("playerId"),
                "playerName": cand.get("playerName"), "priceAmerican": cand["priceAmerican"],
                "modelProb": cand["modelProb"], "fairProb": cand["fairProb"],
            },
            timeout=90,
        )
        if resp.status_code != 200:
            return None  # 503 (AI off) / 403 (no key) => no gate, promote mechanically
        v = resp.json()
    except Exception as exc:  # noqa: BLE001 — the gate must never break record-picks
        who = cand.get("playerName") or cand.get("matchup")
        print(f"[record-picks] debate failed for {who}: {exc}; promoting mechanically")
        return None

    conn.execute(
        """
        INSERT INTO pick_verdicts (
            slate_date, game_id, market, side, line, player_id, player_name, matchup,
            model_prob, fair_prob, edge, ev_pct, price_american, book,
            verdict, confidence, rationale, risks
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
        ON CONFLICT (slate_date, game_id, market, side, player_id) DO UPDATE SET
            verdict=EXCLUDED.verdict, confidence=EXCLUDED.confidence,
            rationale=EXCLUDED.rationale, risks=EXCLUDED.risks, debated_at=now()
        """,
        (slate, cand["gameId"], cand["market"], cand["side"], cand.get("line"),
         cand.get("playerId"), cand.get("playerName"), cand.get("matchup"),
         cand["modelProb"], cand["fairProb"], cand["edge"], cand["evPct"],
         cand["priceAmerican"], cand.get("bestBook"),
         v.get("verdict", "pass"), v.get("confidence"), v.get("rationale"),
         json.dumps(v.get("keyRisks", []))),
    )
    return v.get("verdict", "pass")


def gate_candidates(conn, api: str, slate, candidates: list[dict]) -> list[dict]:
    """Promote up to MAX_PICKS candidates the Analyst endorses, debating in score order.
    verdict bet/lean (or None when the gate is off/unavailable) → promoted; 'pass' → demoted
    (left in pick_verdicts only, surfaced on Best Lines). Cached verdicts are reused."""
    picks: list[dict] = []
    for cand in candidates:
        verdict = _cached_verdict(conn, slate, cand)
        if verdict is None:
            verdict = _debate_and_store(conn, api, slate, cand)
        if verdict is None or verdict in ("bet", "lean"):
            picks.append(cand)
        if len(picks) == MAX_PICKS:
            break
    return picks


def cmd_record_picks(args: argparse.Namespace) -> None:
    api = getattr(args, "api", None) or DEFAULT_API
    # Record the slate users are actually shown, not the wall-clock/projection date — so a
    # pick is "first shown" (and locked) only once its slate is live on the board. An
    # explicit --date still pins it (manual backfills); daily.py leaves date None so the
    # nightly/quick runs self-resolve the active slate.
    slate = args.date if getattr(args, "date", None) is not None else _active_slate(api)

    plays = _get_json(f"{api}/api/odds/best?date={slate}&limit=200")
    try:
        sim = _get_json(f"{api}/api/most-likely?date={slate}")
    except Exception as exc:  # noqa: BLE001 — sim is a corroborator, not a requirement
        print(f"[record-picks] sim unavailable ({exc}); recording without the sim veto")
        sim = None
    try:
        hit_rates = {f"{h['playerId']}:{h['market']}": h
                     for h in _get_json(f"{api}/api/odds/hit-rates?date={slate}")}
    except Exception as exc:  # noqa: BLE001 — like the sim, a veto source, not a requirement
        print(f"[record-picks] hit-rates unavailable ({exc}); recording without that veto")
        hit_rates = None

    candidates = build_candidates(plays, sim, hit_rates)
    now = datetime.now(timezone.utc)

    # Once shown, a pick keeps its row (never DELETE) and its locked line/price. Each run:
    #   1. lineup re-eval — picks whose game lineup changed since lock are re-checked at
    #      their locked terms and lineup-bumped if they no longer clear;
    #   2. budget-gated inserts — new qualifiers are appended only while the slate has
    #      recorded fewer than PICK_BUDGET rows ever. No displacement: a locked pick is
    #      never replaced by a better-looking late play. Started games are frozen as-is.
    conn = get_connection()
    try:
        existing = conn.execute(
            """
            SELECT mp.id, mp.game_id, mp.market, mp.side, mp.player_id, mp.active,
                   g.start_time_utc, mp.bump_reason, mp.lineup_hash, mp.fair_prob,
                   mp.price_american, mp.line
            FROM model_picks mp JOIN games g ON g.id = mp.game_id
            WHERE mp.slate_date = %s
            """,
            (slate,),
        ).fetchall()
        current_hashes = {row[1]: _lineup_hash(conn, row[1]) for row in existing}

        # 1. Lineup re-eval. The current model prob is only fetched for rows the planner
        # can act on (hash changed, game not started, active or lineup-bumped).
        reeval_rows = []
        for (pick_id, gid, market, side, pid, active, start,
             bump_reason, stored_hash, fair_prob, price_am, line) in existing:
            hash_changed = current_hashes[gid] != stored_hash
            started = start is not None and start <= now
            relevant = hash_changed and not started and (active or bump_reason == "lineup")
            mp_now = None
            if relevant:
                mp_now = _current_model_prob(conn, plays, {
                    "game_id": gid, "market": market, "side": side,
                    "player_id": pid, "line": line,
                })
            reeval_rows.append({
                "pick_id": pick_id, "active": active, "bump_reason": bump_reason,
                "start_time": start, "stored_hash": stored_hash,
                "current_hash": current_hashes[gid], "model_prob_now": mp_now,
                "locked_fair_prob": float(fair_prob) if fair_prob is not None else None,
                "locked_price_decimal": american_to_decimal(price_am),
            })
        reeval_ops = plan_lineup_reeval(reeval_rows, now)
        lineup_bumped = unbumped = 0
        for op in reeval_ops:
            if op[0] == "lineup_bump":
                conn.execute(
                    "UPDATE model_picks SET active=false, bumped_at=%s, "
                    "bump_reason='lineup', lineup_hash=%s WHERE id=%s",
                    (now, op[2], op[1]),
                )
                lineup_bumped += 1
            elif op[0] == "unbump":
                conn.execute(
                    "UPDATE model_picks SET active=true, bumped_at=NULL, "
                    "bump_reason=NULL, lineup_hash=%s WHERE id=%s",
                    (op[2], op[1]),
                )
                unbumped += 1
            else:  # "refresh_hash"
                conn.execute(
                    "UPDATE model_picks SET lineup_hash=%s WHERE id=%s",
                    (op[2], op[1]),
                )

        # 2. Budget-gated inserts. Skip the Analyst gate entirely when nothing could
        # change (budget spent, no legacy displaced row to re-promote) — no debate
        # spend on ticks that can't act.
        budget = PICK_BUDGET - len(existing)
        # Re-eval ops above already mutated activity; reflect bumps/unbumps in the map.
        bumped_ids = {op[1] for op in reeval_ops if op[0] == "lineup_bump"}
        unbumped_ids = {op[1] for op in reeval_ops if op[0] == "unbump"}
        existing_by_key = {
            (gid, market, side, pid): (
                pick_id,
                (active or pick_id in unbumped_ids) and pick_id not in bumped_ids,
                start,
                "lineup" if pick_id in bumped_ids else bump_reason,
            )
            for (pick_id, gid, market, side, pid, active, start,
                 bump_reason, *_rest) in existing
        }
        has_legacy = any(reason == "displaced"
                         for (_i, active, _s, reason) in existing_by_key.values()
                         if not active)
        picks: list[dict] = []
        inserted = kept = 0
        if budget > 0 or has_legacy:
            picks = gate_candidates(conn, api, slate, candidates)
            for op in plan_reconcile(picks, existing_by_key, now,
                                     board_loaded=bool(plays), budget=budget):
                if op[0] == "keep":
                    # Legacy transition: re-promote at its original rank; DO NOT touch
                    # the locked line/price/probs.
                    conn.execute(
                        "UPDATE model_picks SET active=true, bumped_at=NULL, "
                        "bump_reason=NULL WHERE id=%s",
                        (op[1],),
                    )
                    kept += 1
                else:  # "insert"
                    _, rank, p = op
                    conn.execute(
                        """
                        INSERT INTO model_picks (
                            slate_date, rank, game_id, market, side, line, player_id,
                            player_name, matchup, model_prob, fair_prob, edge, ev_pct,
                            price_american, book, strong, model_version, recorded_at,
                            first_shown_at, active, lineup_hash
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                                  %s,%s,true,%s)
                        """,
                        (
                            slate, rank, p["gameId"], p["market"], p["side"], p.get("line"),
                            p.get("playerId"), p.get("playerName"), p.get("matchup"),
                            p["modelProb"], p["fairProb"], p["edge"], p["evPct"],
                            p["priceAmerican"], p.get("bestBook"), p["strong"],
                            MODEL_VERSION, now, now,
                            current_hashes.get(p["gameId"]) or _lineup_hash(conn, p["gameId"]),
                        ),
                    )
                    inserted += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"[record-picks] {slate}: {inserted} new, {kept} re-promoted, "
          f"{lineup_bumped} lineup-bumped, {unbumped} re-activated "
          f"({len(existing)} previously recorded, budget {PICK_BUDGET}/slate) "
          f"from {len(plays)} priced plays.")
    for i, p in enumerate(picks, 1):
        who = p.get("playerName") or p.get("matchup")
        print(f"  #{i} {who} {p['market']} {p['side']} {p.get('line')} "
              f"model={p['modelProb']:.3f} fair={p['fairProb']:.3f} edge={p['edge']:+.3f}")


# ── CLV (closing-line value) ────────────────────────────────────────────────

# Opposite side per market, needed to de-vig the closing two-sided price.
_OPPOSITE_SIDE = {"over": "under", "under": "over", "home": "away", "away": "home"}


def _opposite_selection(side: str, line: float | None) -> tuple[str | None, float | None]:
    """(opposite side, opposite side's LINE) for a two-way market.

    Totals share one line (over 8.5 / under 8.5), but handicap markets mirror it:
    run_line home −1.5 pairs with away **+1.5**. Looking the opposite side up at the
    pick's own line finds nothing there — which silently censored CLV for ~all
    run-line picks (2026-07 CLV diagnosis, docs/clv-diagnosis-2026-07.md H3).
    """
    opp = _OPPOSITE_SIDE.get(side)
    if opp is None:
        return None, None
    if side in ("home", "away") and line is not None:
        return opp, -line
    return opp, line


def _devig_two_way(side_decimal: float, opp_decimal: float) -> float | None:
    """De-vig a two-sided market to this side's fair probability (matches OddsService).

        fair = side_implied / (side_implied + opp_implied),   implied = 1 / decimal
    Returns None for non-positive prices.
    """
    if side_decimal <= 0 or opp_decimal <= 0:
        return None
    side_implied = 1.0 / side_decimal
    opp_implied = 1.0 / opp_decimal
    if side_implied + opp_implied <= 0:
        return None
    return side_implied / (side_implied + opp_implied)


def _book_quote(
    conn, game_id: int, market: str, side: str, line: float | None,
    book: str | None, cutoff, player_id: int | None, *, inclusive: bool,
) -> tuple[int | None, float | None, float | None, object]:
    """The pick's selection at its own book as of a cutoff, with a de-vigged fair prob.

    Finds the last odds_snapshots pull for the selection (same player for props, same
    book + line) at or before the cutoff, then reads both sides from that same pull
    (one refresh-odds run shares a captured_at) — the opposite side at its OWN line
    (mirrored for handicaps, see _opposite_selection) — and de-vigs exactly like
    OddsService:
        fair = side_implied / (side_implied + opp_implied),  implied = 1/decimal.
    Returns (price_american, price_decimal, fair_prob, captured_at); any field is None
    when the selection or its opposite side can't be found at the cutoff.

    Both ends of CLV go through this helper — the close (cutoff = first pitch,
    exclusive) AND the bet-time reference (cutoff = first_shown_at, inclusive) — so the
    de-vig basis is identical on both sides. The previous mixed basis (best-of-books at
    bet time vs single-book at close) put a systematic negative offset in every stored
    clv (2026-07 CLV diagnosis, H1).

    Book match is case-insensitive: odds_snapshots.bookmaker stores the lowercase Odds-API
    key ("fanduel") but model_picks.book is observed title-cased ("FanDuel"); LOWER() on
    both bridges them so CLV doesn't silently capture nothing on a case mismatch.
    """
    scope = "prop" if market in ("hit", "hr") else "game"
    cmp = "<=" if inclusive else "<"
    # player_id must match for props (multiple players share a market/line/book); it is
    # NULL for game markets, where IS NOT DISTINCT FROM matches the NULL snapshot rows.
    ts_row = conn.execute(
        f"""
        SELECT MAX(captured_at) FROM odds_snapshots
        WHERE game_id = %s AND scope = %s AND player_id IS NOT DISTINCT FROM %s
          AND market = %s AND side = %s
          AND line IS NOT DISTINCT FROM %s AND LOWER(bookmaker) = LOWER(%s)
          AND captured_at {cmp} %s
        """,
        (game_id, scope, player_id, market, side, line, book, cutoff),
    ).fetchone()
    captured_at = ts_row[0] if ts_row else None
    if captured_at is None:
        return None, None, None, None

    # Both sides at that pull — each at its own line (they differ on handicaps).
    opp_side, opp_line = _opposite_selection(side, line)
    rows = conn.execute(
        """
        SELECT side, line, price_american, price_decimal FROM odds_snapshots
        WHERE game_id = %s AND scope = %s AND player_id IS NOT DISTINCT FROM %s
          AND market = %s AND LOWER(bookmaker) = LOWER(%s) AND captured_at = %s
          AND ((side = %s AND line IS NOT DISTINCT FROM %s)
            OR (side = %s AND line IS NOT DISTINCT FROM %s))
        """,
        (game_id, scope, player_id, market, book, captured_at,
         side, line, opp_side, opp_line),
    ).fetchall()
    prices = {r[0]: (int(r[2]), float(r[3])) for r in rows}
    if side not in prices:
        return None, None, None, captured_at
    price_american, price_decimal = prices[side]

    fair = None
    if opp_side is not None and opp_side in prices:
        fair = _devig_two_way(price_decimal, prices[opp_side][1])
    return price_american, price_decimal, fair, captured_at


def _closing_quote(
    conn, game_id: int, market: str, side: str, line: float | None,
    book: str | None, start_time, player_id: int | None,
) -> tuple[int | None, float | None, float | None, object]:
    """Closing quote = the last pull strictly before first pitch (start_time_utc)."""
    return _book_quote(conn, game_id, market, side, line, book, start_time,
                       player_id, inclusive=False)


def _bettime_quote(
    conn, game_id: int, market: str, side: str, line: float | None,
    book: str | None, first_shown_at, player_id: int | None,
) -> tuple[int | None, float | None, float | None, object]:
    """Bet-time reference quote = the last pull at or before the pick's price lock
    (first_shown_at). Its fair prob is the same-book baseline that clv is measured
    against; stored on the pick as fair_prob_book."""
    return _book_quote(conn, game_id, market, side, line, book, first_shown_at,
                       player_id, inclusive=True)


# ── scoring ───────────────────────────────────────────────────────────────────

def settle_prop(prop_val, scores_present: bool, game_stats_landed: bool) -> str:
    """'grade' | 'void' | 'pending' for a prop pick.

    Scores only persist once the game is final (mlb_api gates backfill-scores on
    abstractGameState == 'Final'), so scores_present doubles as the finality check.
    A final game whose player_game_stats have landed but hold no row for our player
    means he didn't play — VOID, matching how books settle a DNP prop. Locking picks
    off predicted lineups makes this path routine (a predicted starter can sit), so
    it must not strand the pick as pending forever.
    """
    if not scores_present:
        return "pending"
    if prop_val is not None:
        return "grade"
    return "void" if game_stats_landed else "pending"


def _grade(market: str, side: str, line: float | None,
           home: int, away: int, prop_value: int | None) -> tuple[float | None, bool | None]:
    """(result_value, won) for a settled pick; won=None means push (still scored)."""
    if market == "total":
        total = home + away
        if line is None or float(total) == line:
            return float(total), None
        won = total > line if side == "over" else total < line
        return float(total), won
    if market == "moneyline":
        won = home > away if side == "home" else away > home
        return float(home - away if side == "home" else away - home), won
    if market == "run_line":
        margin = (home - away) if side == "home" else (away - home)
        if line is None or margin + line == 0:
            return float(margin), None
        return float(margin), margin + line > 0
    if market in ("hit", "hr"):
        if prop_value is None or line is None:
            return None, None
        won = prop_value > line if side == "over" else prop_value < line
        return float(prop_value), won
    return None, None


def cmd_score_picks(args: argparse.Namespace) -> None:
    slate = args.date if getattr(args, "date", None) is not None \
        else eastern_today() - timedelta(days=1)

    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT mp.id, mp.rank, mp.game_id, mp.market, mp.side, mp.line,
                   mp.player_id, g.home_score, g.away_score, g.detailed_status,
                   CASE mp.market WHEN 'hit' THEN pgs.hits WHEN 'hr' THEN pgs.home_runs END,
                   COALESCE(mp.first_shown_at, mp.recorded_at) AS locked_at,
                   mp.book, g.start_time_utc,
                   EXISTS (SELECT 1 FROM player_game_stats x
                           WHERE x.game_id = mp.game_id) AS game_stats_landed
            FROM model_picks mp
            JOIN games g ON g.id = mp.game_id
            LEFT JOIN player_game_stats pgs
                   ON pgs.player_id = mp.player_id AND pgs.game_id = mp.game_id
            WHERE mp.slate_date = %s AND mp.scored_at IS NULL
            ORDER BY mp.rank NULLS LAST, mp.first_shown_at
            """,
            (slate,),
        ).fetchall()

        scored = pending = voided = clv_n = 0
        record: list[str] = []
        for (pick_id, rank, game_id, market, side, line, player_id,
             home, away, detailed_status, prop_val,
             locked_at, book, start_time, game_stats_landed) in rows:
            tag = f"#{rank}" if rank is not None else "(earlier)"
            if detailed_status in DEAD_GAME_STATUSES:
                # The game won't be played — settle the pick as voided (no win/loss)
                # rather than leaving it pending forever. record-picks normally rebuilds
                # the slate off a board that already excludes dead games, so this only
                # catches a pick recorded before the postponement landed.
                conn.execute(
                    "UPDATE model_picks SET result_value=NULL, won=NULL, scored_at=NOW() "
                    "WHERE id=%s",
                    (pick_id,),
                )
                voided += 1
                record.append(f"  {tag} {market} {side} {line}: VOID ({detailed_status.lower()})")
                continue
            if home is None or away is None:
                pending += 1
                continue  # final score not ingested yet (run backfill-scores first)
            if market in ("hit", "hr") and player_id is not None:
                fate = settle_prop(prop_val, scores_present=True,
                                   game_stats_landed=bool(game_stats_landed))
                if fate == "pending":
                    pending += 1
                    continue  # player stats not ingested yet — retried next run
                if fate == "void":
                    # Final game, stats landed, no row for our player: he didn't play.
                    conn.execute(
                        "UPDATE model_picks SET result_value=NULL, won=NULL, "
                        "scored_at=NOW() WHERE id=%s",
                        (pick_id,),
                    )
                    voided += 1
                    record.append(f"  {tag} {market} {side} {line}: VOID (DNP)")
                    continue
            value, won = _grade(
                market, side, float(line) if line is not None else None,
                int(home), int(away), int(prop_val) if prop_val is not None else None,
            )
            # CLV: same-book de-vigged fair at the price lock vs the same de-vig at the
            # close — one basis at both ends (a mixed best-of-books/single-book basis
            # put a systematic negative offset in every clv; 2026-07 diagnosis, H1).
            # Captured at scoring (the close exists by now); independent of win/loss.
            # Isolated in a SAVEPOINT + try/except: CLV is a measurement nicety and must
            # never roll back or block the pick's grade (a bad closing-odds read would
            # otherwise poison the whole scoring transaction). On any failure we record
            # the grade with CLV NULL.
            close_am = close_dec = close_fair = bet_fair = clv = captured_at = None
            try:
                with conn.transaction():  # SAVEPOINT — a read error rolls back only this
                    close_am, close_dec, close_fair, captured_at = _closing_quote(
                        conn, game_id, market, side,
                        float(line) if line is not None else None, book, start_time,
                        player_id,
                    )
                    _, _, bet_fair, _ = _bettime_quote(
                        conn, game_id, market, side,
                        float(line) if line is not None else None, book, locked_at,
                        player_id,
                    )
                if close_fair is not None and bet_fair is not None:
                    clv = round(close_fair - bet_fair, 4)
                    clv_n += 1
            except Exception as exc:  # noqa: BLE001 — never let CLV break grading
                close_am = close_dec = close_fair = bet_fair = clv = captured_at = None
                print(f"[score-picks] CLV capture failed for pick {pick_id} "
                      f"(grade still recorded): {exc}", file=sys.stderr)
            conn.execute(
                "UPDATE model_picks SET result_value=%s, won=%s, scored_at=NOW(), "
                "close_price_american=%s, close_price_decimal=%s, close_fair_prob=%s, "
                "fair_prob_book=%s, clv=%s, clv_captured_at=%s "
                "WHERE id=%s",
                (value, won, close_am,
                 round(close_dec, 3) if close_dec is not None else None,
                 round(close_fair, 4) if close_fair is not None else None,
                 round(bet_fair, 4) if bet_fair is not None else None,
                 clv, captured_at, pick_id),
            )
            scored += 1
            outcome = "PUSH" if won is None else ("WON" if won else "LOST")
            clv_str = f" clv={clv:+.4f}" if clv is not None else ""
            record.append(f"  {tag} {market} {side} {line}: {outcome} (actual {value}){clv_str}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"[score-picks] {slate}: scored {scored} ({clv_n} with CLV), voided {voided}, "
          f"pending {pending} (voided = game postponed/cancelled; "
          f"pending = missing final score or player stats; re-run after backfills).")
    for line_ in record:
        print(line_)


def cmd_recompute_clv(args: argparse.Namespace) -> None:
    """Re-derive CLV for already-settled picks on the consistent single-book basis.

    One-shot backfill for the 2026-07 CLV diagnosis fixes: historical clv values were
    stored on a mixed de-vig basis (H1) and run-line picks were censored by the
    unmirrored opposite-side lookup (H3). Everything needed to recompute is retained in
    append-only odds_snapshots, so this rewrites close_*, fair_prob_book and clv for
    settled picks in the window. Read-modify-write on measurement columns only — grades
    (result_value/won/scored_at) are never touched.
    """
    since = eastern_today() - timedelta(days=args.days)
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT mp.id, mp.game_id, mp.market, mp.side, mp.line, mp.player_id,
                   COALESCE(mp.first_shown_at, mp.recorded_at) AS locked_at,
                   mp.book, g.start_time_utc, mp.clv
            FROM model_picks mp
            JOIN games g ON g.id = mp.game_id
            WHERE mp.scored_at IS NOT NULL AND mp.slate_date >= %s
            ORDER BY mp.slate_date, mp.id
            """,
            (since,),
        ).fetchall()

        updated = gained = lost = 0
        old_clvs: list[float] = []
        new_clvs: list[float] = []
        for (pick_id, game_id, market, side, line, player_id,
             locked_at, book, start_time, old_clv) in rows:
            line_f = float(line) if line is not None else None
            close_am, close_dec, close_fair, captured_at = _closing_quote(
                conn, game_id, market, side, line_f, book, start_time, player_id)
            _, _, bet_fair, _ = _bettime_quote(
                conn, game_id, market, side, line_f, book, locked_at, player_id)
            clv = round(close_fair - bet_fair, 4) \
                if close_fair is not None and bet_fair is not None else None
            conn.execute(
                "UPDATE model_picks SET close_price_american=%s, close_price_decimal=%s, "
                "close_fair_prob=%s, fair_prob_book=%s, clv=%s, clv_captured_at=%s "
                "WHERE id=%s",
                (close_am,
                 round(close_dec, 3) if close_dec is not None else None,
                 round(close_fair, 4) if close_fair is not None else None,
                 round(bet_fair, 4) if bet_fair is not None else None,
                 clv, captured_at, pick_id),
            )
            updated += 1
            if old_clv is not None:
                old_clvs.append(float(old_clv))
            if clv is not None:
                new_clvs.append(clv)
            if clv is not None and old_clv is None:
                gained += 1
            elif clv is None and old_clv is not None:
                lost += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    def _avg(vals: list[float]) -> str:
        return f"{sum(vals) / len(vals):+.4f}" if vals else "n/a"

    print(f"[recompute-clv] {updated} settled picks since {since}: "
          f"clvN {len(old_clvs)} -> {len(new_clvs)} (+{gained} gained, -{lost} lost), "
          f"avgClv {_avg(old_clvs)} -> {_avg(new_clvs)} "
          f"(consistent single-book basis; grades untouched)")
