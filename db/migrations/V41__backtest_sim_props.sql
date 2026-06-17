-- Monte-Carlo per-batter prop probabilities captured during a backtest run, so the
-- prop-board sim-blend weight can be FIT against actuals (Brier) post-hoc.
-- ============================================================================
-- Populated only when `backtest --sim-props` is passed: the harness runs the same
-- game_sim.py per game (leak-free: snapshot skills, NO bullpen leg) and records the
-- simulator's per-batter estimate alongside the closed-form binomial already stored on
-- the row. The scorer then sweeps w in [0,1] per market over w*sim + (1-w)*closed_form
-- to find the Brier-minimizing blend weight. NULL on rows from runs without --sim-props.

ALTER TABLE backtest_projections
    ADD COLUMN sim_p_hit_1plus NUMERIC(4,3),
    ADD COLUMN sim_p_hr        NUMERIC(4,3),
    ADD COLUMN sim_p_k_1plus   NUMERIC(4,3);
