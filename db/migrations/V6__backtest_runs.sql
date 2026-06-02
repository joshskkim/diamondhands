-- Backtest run registry: one row per backtest execution.
-- Metrics are NULL until the run completes; model_constants captures the
-- exact constants.py snapshot for reproducibility audits.

CREATE TABLE backtest_runs (
    id                   BIGSERIAL PRIMARY KEY,
    started_at           TIMESTAMPTZ DEFAULT NOW(),
    completed_at         TIMESTAMPTZ,
    range_start          DATE        NOT NULL,
    range_end            DATE        NOT NULL,
    model_version        VARCHAR(50) NOT NULL,
    model_constants      JSONB       NOT NULL,
    -- Aggregate counts
    n_games              INT,
    n_batter_projections INT,
    -- Brier scores (lower is better; 0 = perfect)
    brier_hit1plus       NUMERIC(6,5),
    brier_hit2plus       NUMERIC(6,5),
    brier_hr             NUMERIC(6,5),
    brier_k1plus         NUMERIC(6,5),
    -- Game-level MAE (expected vs actual hits per game as runs proxy)
    mae_total_runs       NUMERIC(4,2),
    -- Decile calibration per market, stored as JSONB
    calibration_buckets  JSONB,
    notes                TEXT
);
