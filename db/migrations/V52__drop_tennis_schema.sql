-- Remove the tennis (ATP) feature entirely. The 2nd-sport experiment is being
-- scrapped (too volatile to project reliably); all tennis code, web pages, CLI
-- commands and MCP tools were deleted alongside this migration. Drop every table
-- created by V35–V39. CASCADE + reverse-dependency order clears foreign keys
-- (e.g. odds/projection/stats rows referencing tennis_matches/tennis_players).

DROP TABLE IF EXISTS tennis_prop_odds CASCADE;
DROP TABLE IF EXISTS tennis_total_odds CASCADE;
DROP TABLE IF EXISTS tennis_daily_accuracy CASCADE;
DROP TABLE IF EXISTS tennis_match_odds CASCADE;
DROP TABLE IF EXISTS tennis_match_projections CASCADE;
DROP TABLE IF EXISTS tennis_player_ratings CASCADE;
DROP TABLE IF EXISTS tennis_player_match_stats CASCADE;
DROP TABLE IF EXISTS tennis_matches CASCADE;
DROP TABLE IF EXISTS tennis_tournaments CASCADE;
DROP TABLE IF EXISTS tennis_players CASCADE;
