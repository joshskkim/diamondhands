-- V14: Cache-gating state for odds ingestion.
-- refresh-odds spends The Odds API credits on every run (one slate-wide game-markets
-- call plus one per-event player-props call per game). These columns let the ingester
-- skip the API entirely for a game whose odds-relevant inputs (lineups, weather,
-- probable pitchers) have not changed since the last successful pull.
ALTER TABLE games ADD COLUMN odds_input_hash VARCHAR(64);
ALTER TABLE games ADD COLUMN odds_pulled_at  TIMESTAMPTZ;
