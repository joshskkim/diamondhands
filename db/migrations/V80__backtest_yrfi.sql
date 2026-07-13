-- NRFI/YRFI grading for the backtest. p_yrfi is the closed-form first-inning run prob
-- (yrfi_probability(home_runs, away_runs)) — the SAME number the served NRFI market uses —
-- captured per backtested game so the harness can grade it vs the V53 first-inning actuals
-- (games.home_score_1st + away_score_1st). Closed-form, so it's populated on every run
-- (no --sim-props needed). F5 is NOT graded — no first-5-innings actuals are stored.
ALTER TABLE backtest_game_runs ADD COLUMN p_yrfi NUMERIC(4,3);
