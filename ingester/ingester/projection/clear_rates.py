"""As-of-date season clear rates for the projection engine's hit blend.

The empirical-shrinkage blend (prop_blend.py) regresses a batter's model P(hit>=1) toward
his demonstrated season clear rate. This is the Python source of that rate, ported from the
API's ClearRateRepository so the engine-time and serve-time numbers agree.

Leak-free by construction: only games STRICTLY BEFORE ``as_of`` count, so scoring a slate
never sees its own outcome. In the live path ``as_of`` is the slate date; in the backtest
path it's the game-day being projected.
"""
from __future__ import annotations

from datetime import date

import psycopg

# Season slice of ClearRateRepository.RATES_BATCH_SQL (no L10 — the blend uses season only):
# share of the player's in-season games (before the slate, with a real PA) that cleared 1+ hit.
_SEASON_HIT_RATES_SQL = """
    SELECT player_id,
           AVG((hits > 0)::int) AS hit_season,
           COUNT(*)             AS n_season
    FROM player_game_stats
    WHERE player_id = ANY(%s)
      AND game_date >= %s        -- season start (Jan 1 of the slate's year)
      AND game_date <  %s        -- strictly before the slate: no same-day leak
      AND plate_appearances > 0
    GROUP BY player_id
"""


def season_hit_rates(
    conn: psycopg.Connection,
    player_ids: list[int],
    as_of: date,
) -> dict[int, tuple[float | None, int]]:
    """Season hit clear rate + game count per player, as of ``as_of`` (one query).

    Returns ``{player_id: (rate, n)}``. A player with no qualifying in-season game before
    ``as_of`` is absent from the map — callers read that as ``(None, 0)``, which the blend
    treats as "regress toward the league rate."
    """
    if not player_ids:
        return {}
    season_start = date(as_of.year, 1, 1)
    rows = conn.execute(
        _SEASON_HIT_RATES_SQL, (list(player_ids), season_start, as_of)
    ).fetchall()
    return {
        int(pid): (None if rate is None else float(rate), int(n))
        for pid, rate, n in rows
    }
