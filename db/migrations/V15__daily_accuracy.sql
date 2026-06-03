-- Ongoing daily projection-accuracy tracking.
-- ============================================================================
-- The CLI `backtest` command scores accuracy post-hoc over a date range and
-- writes a single backtest_runs row. This table instead stores one snapshot
-- PER SLATE DATE per market, written by `compute-accuracy` (chained into the
-- nightly `daily` run), so the API/web can plot a rolling accuracy trend and
-- the latest calibration curve without re-running a full backtest.
--
-- One row per (slate_date, model_version, market). Markets:
--   hit1plus | hit2plus | hr | k1plus  — binary props (Brier + calibration)
--   total_runs                          — game run totals (MAE only)
--
-- brier / baseline_brier / ece / calibration_buckets are populated for the
-- binary markets; mae is populated only for total_runs (NULL elsewhere).
CREATE TABLE daily_accuracy (
    slate_date          DATE         NOT NULL,
    model_version       VARCHAR(20)  NOT NULL,
    market              VARCHAR(20)  NOT NULL,   -- hit1plus|hit2plus|hr|k1plus|total_runs
    n                   INT          NOT NULL,   -- sample size scored for this market/date
    brier               NUMERIC(7,5),            -- NULL for total_runs
    baseline_brier      NUMERIC(7,5),            -- always-predict-the-mean baseline; NULL for total_runs
    ece                 NUMERIC(7,5),            -- expected calibration error; NULL for total_runs
    calibration_buckets JSONB,                   -- [{lo,hi,n,predicted_mean,actual_rate}, …]
    mae                 NUMERIC(6,3),            -- mean abs error on total runs; NULL for binary markets
    computed_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (slate_date, model_version, market)
);

CREATE INDEX idx_daily_accuracy_date ON daily_accuracy(slate_date DESC);
