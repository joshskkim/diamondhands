-- Per-start pitcher projections (the probable starter's expected line).
-- ============================================================================
-- Derived from the SAME per-batter projections we already compute: the opposing
-- lineup's projected per-PA outcomes vs this starter, aggregated over the batters
-- he is expected to face (STARTER_PA_SHARE of the lineup's plate appearances).
-- So every factor in the batter model (pitch-mix matchup, handedness, park, weather)
-- flows through to the pitcher line. Bullpen / times-through-order beyond the share
-- are not yet modeled (the starter's share is a flat ~60%); refine later.

CREATE TABLE pitcher_projections (
    game_id        BIGINT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    pitcher_id     INT    NOT NULL REFERENCES players(id),
    is_home        BOOLEAN NOT NULL,             -- is the pitcher's team the home team
    expected_bf    NUMERIC(5,2),                 -- batters faced
    expected_outs  NUMERIC(5,2),
    expected_ip    NUMERIC(4,2),
    expected_k     NUMERIC(5,2),
    expected_h     NUMERIC(5,2),
    expected_hr    NUMERIC(4,2),
    expected_bb    NUMERIC(4,2),
    expected_runs  NUMERIC(4,2),                 -- runs allowed while in the game (approx)
    computed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (game_id, pitcher_id)
);

CREATE INDEX idx_pitcher_projections_game ON pitcher_projections(game_id);
