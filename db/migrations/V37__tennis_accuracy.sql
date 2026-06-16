-- Diamond — Tennis Milestone 3: model accuracy / results tracking
-- =============================================================================
-- Out-of-sample match-winner performance, bucketed by month x surface. Mirrors
-- the MLB daily_accuracy table (V15). Populated by `tennis-score` (walk-forward).

CREATE TABLE tennis_daily_accuracy (
    period_date         DATE NOT NULL,                 -- first day of the month bucket
    model_version       VARCHAR(20) NOT NULL,
    surface             VARCHAR(10) NOT NULL,          -- 'all' | 'hard' | 'clay' | 'grass'
    market              VARCHAR(20) NOT NULL DEFAULT 'match_winner',
    n                   INT NOT NULL,
    brier               NUMERIC(7,5),
    baseline_brier      NUMERIC(7,5),                  -- always-predict-base-rate
    ece                 NUMERIC(7,5),                  -- expected calibration error
    calibration_buckets JSONB,                         -- [{lo,hi,n,predictedMean,actualRate}, ...]
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (period_date, model_version, surface, market)
);

CREATE INDEX idx_tennis_accuracy_surface ON tennis_daily_accuracy(surface, period_date);
