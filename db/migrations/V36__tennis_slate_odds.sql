-- Diamond — Tennis Milestone 2: live slate + match-winner odds
-- =============================================================================
-- Adds the columns a live (upcoming) match needs and a table for sportsbook
-- match-winner (h2h) quotes. Historical rows keep NULL start_time/odds_event_id.

ALTER TABLE tennis_matches
    ADD COLUMN start_time_utc TIMESTAMPTZ,   -- match start (scheduled rows); NULL for historical
    ADD COLUMN odds_event_id  VARCHAR(64);   -- The Odds API event id (for odds matching)

-- Find today's scheduled matches quickly.
CREATE INDEX idx_tennis_matches_status_date ON tennis_matches(status, match_date);
-- Idempotent slate upserts keyed by the Odds API event id (scheduled rows only).
CREATE UNIQUE INDEX idx_tennis_matches_event ON tennis_matches(odds_event_id)
    WHERE odds_event_id IS NOT NULL;

-- Match-winner (h2h) quotes per book. Parallels game_odds; sides are the match's
-- player_a / player_b slots (tennis has no home/away). Raw quotes — de-vig + EV are
-- computed in the API (TennisService), not stored.
CREATE TABLE tennis_match_odds (
    id             BIGSERIAL PRIMARY KEY,
    match_id       BIGINT REFERENCES tennis_matches(id) ON DELETE CASCADE,
    bookmaker      VARCHAR(40) NOT NULL,
    side           VARCHAR(10) NOT NULL,        -- 'player_a' | 'player_b'
    price_american INT NOT NULL,
    price_decimal  NUMERIC(8,3) NOT NULL,
    implied_prob   NUMERIC(6,4) NOT NULL,
    last_update    TIMESTAMPTZ,
    fetched_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (match_id, bookmaker, side)
);

CREATE INDEX idx_tennis_match_odds_match ON tennis_match_odds(match_id);
