-- First-inning run projection (NRFI / YRFI) per game.
-- ============================================================================
-- YRFI = "yes run, first inning" (>=1 run scored by either team in the 1st);
-- NRFI = no run. Derived from each team's projected full-game runs scaled to the
-- first inning (which the top of the order leads off), then a calibrated
-- expected-runs -> P(score) mapping, combined across both halves:
--   p_yrfi = 1 - (1 - P(home scores T1)) * (1 - P(away scores T1))
-- Calibrated so a league-average matchup yields ~0.50 YRFI. nrfi = 1 - p_yrfi.

ALTER TABLE game_projections ADD COLUMN p_yrfi NUMERIC(4,3);                 -- P(>=1 run in the 1st)
ALTER TABLE game_projections ADD COLUMN expected_first_inning_runs NUMERIC(4,2);
