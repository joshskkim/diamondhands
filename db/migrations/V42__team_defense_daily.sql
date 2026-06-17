-- Per-team, per-day defensive ball-in-play aggregates (hit suppression vs expected).
-- ============================================================================
-- For every in-park ball in play a team's defense faced on a given date, we record the
-- count, the actual non-HR hits allowed, and the sum of Statcast xBA
-- (estimated_ba_using_speedangle) on those balls. A team that allows FEWER hits than xBA
-- expects is suppressing hits with defense (the batter's contact quality is held constant
-- by xBA). The projector reads season-to-date rows STRICTLY BEFORE a slate (leak-free),
-- shrinks the actual/expected ratio toward 1.0 by sample size, and scales each opposing
-- batter's non-HR hit rate by the result. HR is excluded (not fielded).
--
-- Backtested (Jun 2026): leak-free −0.40% hit Brier on the full 2025 season, monotonic.
-- Populated by `refresh-team-defense`; one row per (defending team, game date).

CREATE TABLE team_defense_daily (
    team_id     INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    game_date   DATE    NOT NULL,
    bip         INTEGER NOT NULL,            -- in-park balls in play faced on defense
    act_hits    INTEGER NOT NULL,            -- actual non-HR hits allowed on those BIP
    exp_hits    NUMERIC(7,3) NOT NULL,       -- Σ xBA on those BIP (expected hits)
    computed_at TIMESTAMPTZ DEFAULT NOW(),

    PRIMARY KEY (team_id, game_date)
);
