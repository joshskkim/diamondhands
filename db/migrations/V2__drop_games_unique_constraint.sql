-- Drop the UNIQUE(game_date, home_team_id, away_team_id) constraint from games.
--
-- Rationale: MLB schedules occasional doubleheaders where the same two teams
-- play twice on the same calendar date.  The games table's PRIMARY KEY is
-- already games.id (= MLB game_pk), so individual-game uniqueness is
-- guaranteed by the PK.  The natural-key constraint is therefore both
-- redundant and harmful.
ALTER TABLE games
    DROP CONSTRAINT games_game_date_home_team_id_away_team_id_key;
