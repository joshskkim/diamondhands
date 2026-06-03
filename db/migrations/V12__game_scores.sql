-- Actual final scores per game (v3 runs/totals work).
-- Backfilled from the MLB Stats API schedule (teams.home/away.score on Final games).
-- Enables evaluating the team-run / totals projection — previously impossible because
-- only the hits proxy was available (see backtest MAE notes).
ALTER TABLE games ADD COLUMN home_score INT;
ALTER TABLE games ADD COLUMN away_score INT;
