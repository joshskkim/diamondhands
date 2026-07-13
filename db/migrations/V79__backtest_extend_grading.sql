-- Extend the backtest harness to grade the markets we actually serve but never scored:
-- pitcher props and the run line. (Batter total bases already had a column — V5 —
-- so it needed no schema.) Written by _project_game_backtest; leak-free (snapshot
-- batter projections + start history strictly before the as-of snapshot).
-- ============================================================================

-- Per-start pitcher projection captured during a backtest run, mirroring the served
-- pitcher_projections table (V23/V33) plus the backtest_run_id FK. Graded post-hoc
-- against pitcher_starts (V31: outs/K/BB/hits/HR/ER/BF actuals). The workload jsonb
-- carries the P(outs>line)/P(K>line)/P(BB>line) ladders so the canonical-line props
-- get a real Brier, not just a count MAE.
CREATE TABLE backtest_pitcher_projections (
    backtest_run_id BIGINT  NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    game_id         BIGINT  NOT NULL REFERENCES games(id),
    pitcher_id      INT     NOT NULL REFERENCES players(id),
    is_home         BOOLEAN NOT NULL,
    expected_bf     NUMERIC(5,2),
    expected_outs   NUMERIC(5,2),
    expected_ip     NUMERIC(4,2),
    expected_k      NUMERIC(5,2),
    expected_h      NUMERIC(5,2),
    expected_hr     NUMERIC(4,2),
    expected_bb     NUMERIC(4,2),
    expected_runs   NUMERIC(4,2),
    workload        jsonb,
    PRIMARY KEY (backtest_run_id, game_id, pitcher_id)
);

CREATE INDEX idx_btpp_run ON backtest_pitcher_projections(backtest_run_id);

-- Run-line grading. backtest_game_runs (V19) stored only the expected TOTAL; the run
-- line needs the home/away split and P(home covers -1.5) so we can grade the favorite's
-- -1.5 / underdog's +1.5 cover as a probability market vs the actual margin
-- (games.home_score - away_score). p_home_cover_1_5 is populated only on --sim-props runs
-- (the margin distribution comes from the Monte-Carlo sim); NULL otherwise.
ALTER TABLE backtest_game_runs
    ADD COLUMN home_expected_runs NUMERIC(5,2),
    ADD COLUMN away_expected_runs NUMERIC(5,2),
    ADD COLUMN p_home_cover_1_5   NUMERIC(4,3);
