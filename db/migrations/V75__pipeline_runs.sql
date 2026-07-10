-- Pipeline run-log: throughput + latency observability for the `daily` command.
-- ============================================================================
-- cmd_daily already timed every step and printed it, but the numbers evaporated with
-- the container logs, so there was no defensible answer to "how long does a slate
-- projection take" or "how much does the ingest write per day". These tables persist
-- both, one row per run and one per step.
--
-- Row counts are NOT computed by the commands. They are deltas of pg_stat_user_tables
-- (n_tup_ins/upd/del) snapshotted around each step by ingester/runlog.py, which is why
-- none of the cmd_* step functions had to change to report a count.
--
-- CAVEAT 1 — what a "row" is here. n_tup_* counts TUPLE WRITE OPERATIONS, not distinct
-- rows: an UPSERT that updates increments n_tup_upd, an ON CONFLICT that inserts
-- increments n_tup_ins, and a HOT update still increments n_tup_upd. These columns are
-- therefore "row writes", an over-count of unique rows touched. Phrase results as
-- insert/update/delete operations, never as "N unique rows".
--
-- CAVEAT 2 — attribution, and why `mode` exists. pg_stat_user_tables is DATABASE-WIDE,
-- not per-session: the delta includes every backend's writes, not just ours. The 9am
-- full run (cron `0 9 * * *`) does not overlap the live-refresh loop (`13-23,0-2`) or
-- meaningful API traffic, so its deltas are cleanly attributable to the pipeline. The
-- `*/30 12-23` quick runs DO overlap both and their deltas are polluted. Quick runs are
-- logged for completeness; any headline number must filter mode = 'full'.

-- Run header: one row per cmd_daily invocation. 'running' means the process died before
-- finish() — cmd_daily wraps the step loop in try/finally, so even a fatal `project`
-- failure lands here as 'fail' rather than leaving the row stuck in 'running'.
CREATE TABLE pipeline_runs (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mode           TEXT        NOT NULL CHECK (mode IN ('full', 'quick')),
    slate_date     DATE        NOT NULL,
    status         TEXT        NOT NULL DEFAULT 'running'
                               CHECK (status IN ('running', 'ok', 'warn', 'fail')),
    step_count     INTEGER     NOT NULL DEFAULT 0,
    warning_count  INTEGER     NOT NULL DEFAULT 0,
    -- Sum of the per-step clamped deltas below, so inter-step gaps are excluded.
    rows_inserted  BIGINT      NOT NULL DEFAULT 0,
    rows_updated   BIGINT      NOT NULL DEFAULT 0,
    rows_deleted   BIGINT      NOT NULL DEFAULT 0,
    duration_ms    INTEGER,
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at    TIMESTAMPTZ
);

CREATE INDEX idx_pipeline_runs_mode_started ON pipeline_runs (mode, started_at DESC);

-- Per-step detail. tables_json holds ONLY the tables with a nonzero delta for this step
-- ({"model_picks": {"ins": 812, "upd": 0, "del": 812}}), keeping the blob small and the
-- step's story auditable after the fact.
--
-- Note: the 'close prior slate' and 'grade today' steps swallow their own sub-step
-- failures, so they always record status='ok' and their row delta is the SUM of every
-- sub-step they ran.
CREATE TABLE pipeline_run_steps (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id         BIGINT      NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    step_index     INTEGER     NOT NULL,
    name           TEXT        NOT NULL,
    status         TEXT        NOT NULL CHECK (status IN ('ok', 'warn', 'fail')),
    duration_ms    INTEGER     NOT NULL,
    rows_inserted  BIGINT      NOT NULL DEFAULT 0,
    rows_updated   BIGINT      NOT NULL DEFAULT 0,
    rows_deleted   BIGINT      NOT NULL DEFAULT 0,
    tables_json    JSONB,
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_pipeline_run_steps_run ON pipeline_run_steps (run_id, step_index);
-- Serves "median duration of the `project` step across full runs".
CREATE INDEX idx_pipeline_run_steps_name_status ON pipeline_run_steps (name, status);
