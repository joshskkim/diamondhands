-- MLB's status.abstractGameState (stored in games.status) only reports
-- Preview/Live/Final — it never surfaces Postponed/Suspended/Cancelled, which live
-- in status.detailedState. The daily projector needs the detailed state so it can
-- skip games that won't be played as scheduled.
ALTER TABLE games ADD COLUMN detailed_status VARCHAR(40);
