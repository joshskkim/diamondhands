-- Sportsbook odds (compare books + evaluate edge vs. our projection model).
-- ============================================================================
-- Source: The Odds API (the-odds-api.com). We store every book's price per
-- market so the API can surface the *best line* for the day and compute EV%
-- against our model probabilities (batter_projections / game_projections).
--
-- Markets are normalized to canonical keys so the provider's wire names never
-- leak past the ingester:
--   game markets : moneyline (h2h) | run_line (spreads) | total (totals)
--   player props : hit (batter_hits) | hr (batter_home_runs)
--                 | pitcher_k (pitcher_strikeouts) | pitcher_outs (pitcher_outs)

-- The Odds API event id for this game, set when an odds event is matched to our
-- slate by date + home/away team. NULL until odds have been pulled.
ALTER TABLE games ADD COLUMN odds_event_id VARCHAR(64);

-- One row per (book, market, side, line) for game-level markets.
-- price_decimal / implied_prob are derived from price_american at ingest time
-- so the API can rank lines without re-deriving. implied_prob includes vig.
CREATE TABLE game_odds (
    id              BIGSERIAL PRIMARY KEY,
    game_id         BIGINT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    bookmaker       VARCHAR(40)  NOT NULL,
    market          VARCHAR(20)  NOT NULL,   -- moneyline | run_line | total
    side            VARCHAR(10)  NOT NULL,   -- home | away | over | under
    line            NUMERIC(5,2),            -- NULL for moneyline; ±run line; total points
    price_american  INT          NOT NULL,
    price_decimal   NUMERIC(7,3) NOT NULL,
    implied_prob    NUMERIC(6,4) NOT NULL,
    last_update     TIMESTAMPTZ,             -- book's last_update from the provider
    fetched_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (game_id, bookmaker, market, side, line)
);

CREATE INDEX idx_game_odds_game ON game_odds(game_id);

-- One row per (book, player, market, side, line) for player props.
-- Only rows whose player matched a known players.id are stored (edge-ready);
-- player_name keeps the provider description for display without a re-join.
CREATE TABLE player_prop_odds (
    id              BIGSERIAL PRIMARY KEY,
    game_id         BIGINT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    player_id       INT NOT NULL REFERENCES players(id),
    player_name     VARCHAR(100) NOT NULL,
    market          VARCHAR(20)  NOT NULL,   -- hit | hr | pitcher_k | pitcher_outs
    side            VARCHAR(10)  NOT NULL,   -- over | under
    line            NUMERIC(5,2) NOT NULL,
    price_american  INT          NOT NULL,
    price_decimal   NUMERIC(7,3) NOT NULL,
    implied_prob    NUMERIC(6,4) NOT NULL,
    bookmaker       VARCHAR(40)  NOT NULL,
    last_update     TIMESTAMPTZ,
    fetched_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (game_id, player_id, market, side, line, bookmaker)
);

CREATE INDEX idx_prop_odds_game   ON player_prop_odds(game_id);
CREATE INDEX idx_prop_odds_player ON player_prop_odds(player_id);
