-- Full-game run-line cover probabilities from the Monte-Carlo game simulator.
-- ============================================================================
-- The sim already produces the full joint (home_runs, away_runs) distribution per game;
-- these two columns persist the standard ±1.5 run-line cover probabilities computed
-- directly from that joint distribution (mean over sims of margin > 1.5 / margin < 1.5).
-- This is more faithful than the independent-Poisson approximation OddsService still uses
-- for arbitrary alt lines, and powers the Run Line card on Today's Board (replacing F5).
-- Integer run margins never land on a .5 line, so the two probabilities sum to 1.

ALTER TABLE game_sim_projections
    ADD COLUMN p_home_cover_1_5 NUMERIC(4,3),   -- P(home covers -1.5)
    ADD COLUMN p_away_cover_1_5 NUMERIC(4,3);   -- P(away covers +1.5)
