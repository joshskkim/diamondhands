-- Diamond — Tennis: ace / double-fault player-prop odds
-- =============================================================================
-- Per-player over/under prop quotes (aces, double faults). model_prob is the
-- model's P(side) at this book's line, computed at ingestion from the Negative
-- Binomial count distribution (serve-rate mean × φ dispersion).

CREATE TABLE tennis_prop_odds (
    id             BIGSERIAL PRIMARY KEY,
    match_id       BIGINT REFERENCES tennis_matches(id) ON DELETE CASCADE,
    player_id      VARCHAR(12) REFERENCES tennis_players(id),
    market         VARCHAR(10) NOT NULL,        -- 'aces' | 'dfs'
    side           VARCHAR(10) NOT NULL,        -- 'over' | 'under'
    line           NUMERIC(5,1) NOT NULL,
    bookmaker      VARCHAR(40) NOT NULL,
    price_american INT NOT NULL,
    price_decimal  NUMERIC(8,3) NOT NULL,
    implied_prob   NUMERIC(6,4) NOT NULL,
    model_prob     NUMERIC(6,4),
    last_update    TIMESTAMPTZ,
    fetched_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (match_id, player_id, market, side, line, bookmaker)
);

CREATE INDEX idx_tennis_prop_odds_match ON tennis_prop_odds(match_id);
