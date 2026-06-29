"""score-agent-recs: grade agent recommendations (and user bets) against actual results.

This is the eval-first payoff: agent_recommendations and user_bets carry the SAME selection
identity + grade columns as model_picks, so grading is a near-clone of
``commands.picks.cmd_score_picks`` that imports its battle-tested internals verbatim
(_grade, _closing_quote, DEAD_GAME_STATUSES). The regression guarantee: an agent rec and the
equivalent model_picks row for the same selection grade to identical won/result_value/clv —
the score-picks code is the single source of truth for "did this bet win, and was it good".
"""
from __future__ import annotations

import argparse
import sys
from datetime import timedelta

from ingester.db import eastern_today, get_connection
from ingester.projection.constants import DEAD_GAME_STATUSES
# Reuse the exact grading + CLV machinery (do NOT re-implement — that's the whole point).
from ingester.commands.picks import _grade, _closing_quote


def _score_table(conn, table: str, slate, has_fair: bool) -> tuple[int, int, int, int]:
    """Grade unscored rows in `table` for `slate`. Returns (scored, voided, pending, clv_n).

    `has_fair` is True for agent_recommendations (which store the bet-time de-vigged fair_prob,
    so CLV = close_fair - fair_prob is computable) and False for user_bets (no bet-time fair,
    so we still capture the closing quote but leave clv NULL).
    """
    fair_col = "r.fair_prob" if has_fair else "NULL::numeric"
    rows = conn.execute(
        f"""
        SELECT r.id, r.game_id, r.market, r.side, r.line, r.player_id,
               g.home_score, g.away_score, g.detailed_status,
               CASE r.market WHEN 'hit' THEN pgs.hits WHEN 'hr' THEN pgs.home_runs END,
               {fair_col}, r.book, g.start_time_utc
        FROM {table} r
        JOIN games g ON g.id = r.game_id
        LEFT JOIN player_game_stats pgs
               ON pgs.player_id = r.player_id AND pgs.game_id = r.game_id
        WHERE r.slate_date = %s AND r.scored_at IS NULL
        ORDER BY r.id
        """,
        (slate,),
    ).fetchall()

    scored = voided = pending = clv_n = 0
    for (rid, game_id, market, side, line, player_id,
         home, away, detailed_status, prop_val, fair_prob, book, start_time) in rows:
        if detailed_status in DEAD_GAME_STATUSES:
            conn.execute(
                f"UPDATE {table} SET result_value=NULL, won=NULL, scored_at=NOW() WHERE id=%s",
                (rid,),
            )
            voided += 1
            continue
        if home is None or away is None:
            pending += 1
            continue
        if market in ("hit", "hr") and prop_val is None and player_id is not None:
            pending += 1
            continue
        value, won = _grade(
            market, side, float(line) if line is not None else None,
            int(home), int(away), int(prop_val) if prop_val is not None else None,
        )
        # CLV: same SAVEPOINT-isolated capture as score-picks — never let it break the grade.
        close_am = close_dec = close_fair = clv = captured_at = None
        try:
            with conn.transaction():
                close_am, close_dec, close_fair, captured_at = _closing_quote(
                    conn, game_id, market, side,
                    float(line) if line is not None else None, book, start_time, player_id,
                )
            if close_fair is not None and fair_prob is not None:
                clv = round(close_fair - float(fair_prob), 4)
                clv_n += 1
        except Exception as exc:  # noqa: BLE001 — CLV is a nicety, never block grading
            close_am = close_dec = close_fair = clv = captured_at = None
            print(f"[score-agent-recs] CLV capture failed for {table} {rid} "
                  f"(grade still recorded): {exc}", file=sys.stderr)
        conn.execute(
            f"UPDATE {table} SET result_value=%s, won=%s, scored_at=NOW(), "
            "close_price_american=%s, close_price_decimal=%s, close_fair_prob=%s, "
            "clv=%s, clv_captured_at=%s WHERE id=%s",
            (value, won, close_am,
             round(close_dec, 3) if close_dec is not None else None,
             round(close_fair, 4) if close_fair is not None else None,
             clv, captured_at, rid),
        )
        scored += 1
    return scored, voided, pending, clv_n


def cmd_score_agent_recs(args: argparse.Namespace) -> None:
    slate = args.date if getattr(args, "date", None) is not None \
        else eastern_today() - timedelta(days=1)

    conn = get_connection()
    try:
        rec = _score_table(conn, "agent_recommendations", slate, has_fair=True)
        bet = _score_table(conn, "user_bets", slate, has_fair=False)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"[score-agent-recs] {slate}: "
          f"recommendations scored {rec[0]} ({rec[3]} with CLV), voided {rec[1]}, pending {rec[2]}; "
          f"user bets scored {bet[0]}, voided {bet[1]}, pending {bet[2]}.")
