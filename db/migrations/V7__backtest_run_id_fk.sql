-- Wire up the FK from backtest_projections to backtest_runs now that V6 exists.
-- Orphaned rows (from ad-hoc 'project --as-of' runs using date-derived IDs)
-- are cleared first to allow the constraint to be applied cleanly.

TRUNCATE backtest_projections;

ALTER TABLE backtest_projections
    ADD CONSTRAINT fk_backtest_projections_run
    FOREIGN KEY (backtest_run_id) REFERENCES backtest_runs(id) ON DELETE CASCADE;
