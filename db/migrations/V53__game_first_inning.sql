-- First-inning runs per side, for grading NRFI/YRFI leans against actuals.
-- Populated by backfill-scores (schedule hydrated with linescore). NULL until the
-- top+bottom of the 1st have completed.
ALTER TABLE games
    ADD COLUMN IF NOT EXISTS home_score_1st INT,
    ADD COLUMN IF NOT EXISTS away_score_1st INT;
