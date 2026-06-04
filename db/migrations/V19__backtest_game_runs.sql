-- Real run-total scoring for the backtest.
-- ============================================================================
-- The backtest previously left team-run totals unscored: _project_game_backtest
-- computed expected runs but discarded them, and backtest_runs.mae_total_runs was
-- actually a per-game HITS proxy. This stores the model's predicted game total per
-- backtested game so the harness can compute a real run MAE + correlation against
-- the final score (games.home_score + away_score).

CREATE TABLE backtest_game_runs (
    backtest_run_id     BIGINT  NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    game_id             BIGINT  NOT NULL REFERENCES games(id),
    expected_total_runs NUMERIC(5,2) NOT NULL,
    PRIMARY KEY (backtest_run_id, game_id)
);

-- Discrimination + a naive baseline alongside the (now real) run MAE.
ALTER TABLE backtest_runs ADD COLUMN run_corr         NUMERIC(5,3);
ALTER TABLE backtest_runs ADD COLUMN run_mae_baseline NUMERIC(5,2);

-- mae_total_runs is repurposed from a hits-per-game proxy to the real
-- |predicted - actual| game-total run MAE (V19+). Pre-V19 rows hold the old proxy.
COMMENT ON COLUMN backtest_runs.mae_total_runs IS
    'Real |predicted - actual| game-total run MAE (V19+; pre-V19 rows = hits-per-game proxy).';
