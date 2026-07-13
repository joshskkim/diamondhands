-- Per-batter total-bases distribution captured during a --sim-props backtest, so TB can be
-- graded as a probabilistic market (2+TB Brier, whole-distribution CRPS) — not just the
-- count-MAE the stored expected_total_bases already allows. The pmf is BatterProps.tb_hist
-- (Monte-Carlo counts, bins 0..10 with the last a >= bin) normalized to probabilities.
-- NULL on rows from runs without --sim-props.
ALTER TABLE backtest_projections ADD COLUMN sim_tb_pmf jsonb;
