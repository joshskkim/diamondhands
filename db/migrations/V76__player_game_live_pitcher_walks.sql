-- Live (in-progress) walks-allowed for a starter, so the pitcher_walks prop card can be
-- graded while a game is running. Final grading reads pitcher_starts.walks (already
-- present, V31); this column mirrors it for player_game_live's Final-shaped live reads.
ALTER TABLE player_game_live ADD COLUMN IF NOT EXISTS pitcher_walks INT;
