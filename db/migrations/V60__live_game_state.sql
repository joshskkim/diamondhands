-- Live in-game state for real-time bet/board tracking. Distinct from the Final
-- columns (home_score/away_score) so the Final grading path (score-picks, results)
-- never settles on provisional data. Populated by `live-refresh` (schedule hydrated
-- with linescore) while a game is in progress; NULL for scheduled games.
ALTER TABLE games
    ADD COLUMN IF NOT EXISTS live_home_score     INT,
    ADD COLUMN IF NOT EXISTS live_away_score     INT,
    ADD COLUMN IF NOT EXISTS live_current_inning INT,          -- linescore.currentInning
    ADD COLUMN IF NOT EXISTS live_inning_state   VARCHAR(10),  -- Top/Middle/Bottom/End
    ADD COLUMN IF NOT EXISTS live_is_top         BOOLEAN,      -- linescore.isTopInning
    ADD COLUMN IF NOT EXISTS live_updated_at     TIMESTAMPTZ;
