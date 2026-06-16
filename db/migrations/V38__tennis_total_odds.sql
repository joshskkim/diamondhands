-- Diamond — Tennis: total-games (over/under) odds
-- =============================================================================
-- Parallels tennis_match_odds but for the total-games market. model_prob is the
-- model's P(side) at this book's line (computed at ingestion from the calibrated
-- games distribution), so the API just de-vigs + computes EV.

CREATE TABLE tennis_total_odds (
    id             BIGSERIAL PRIMARY KEY,
    match_id       BIGINT REFERENCES tennis_matches(id) ON DELETE CASCADE,
    bookmaker      VARCHAR(40) NOT NULL,
    side           VARCHAR(10) NOT NULL,        -- 'over' | 'under'
    line           NUMERIC(5,1) NOT NULL,       -- total games line (e.g. 22.5)
    price_american INT NOT NULL,
    price_decimal  NUMERIC(8,3) NOT NULL,
    implied_prob   NUMERIC(6,4) NOT NULL,
    model_prob     NUMERIC(6,4),                -- model P(this side) at this line
    last_update    TIMESTAMPTZ,
    fetched_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (match_id, bookmaker, side, line)
);

CREATE INDEX idx_tennis_total_odds_match ON tennis_total_odds(match_id);
