-- Per-batter true-talent xHR rate (Phase 2.3), aggregated from the learned xHR model.
-- ============================================================================
-- Each batter's balls in play (batted_ball_events) are scored by the xHR model and
-- averaged into a park-neutral expected-HR-per-batted-ball, then empirical-Bayes
-- regressed toward the league xHR rate by sample size. This is a leak-free, fast-
-- stabilizing true-power estimate: prior-season xhr_per_bb feeds the next season's
-- HR projection (season here = the season the profile is measured FROM, exactly like
-- batter_batted_ball / _load_barrel_rates).

CREATE TABLE batter_xhr (
    player_id    INT     NOT NULL REFERENCES players(id),
    season       INT     NOT NULL,
    bip          INT     NOT NULL,           -- balls in play scored (sample size)
    xhr_per_bb   NUMERIC(6,5),               -- EB-shrunk expected HR per batted ball
    raw_xhr_per_bb NUMERIC(6,5),             -- unshrunk mean model score (diagnostic)
    updated_at   TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (player_id, season)
);

CREATE INDEX idx_batter_xhr_season ON batter_xhr(season);
