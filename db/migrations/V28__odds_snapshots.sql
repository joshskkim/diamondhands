-- Append-only odds history for line-movement tracking.
--
-- player_prop_odds / game_odds hold only the LATEST price per selection (refresh-odds
-- delete-then-reinserts each game), so open→current movement can't be reconstructed
-- from them. This table captures a timestamped copy of every quote on each refresh-odds
-- pull; querying ordered by captured_at then yields the movement.
--
-- One unified table covers both game markets (scope='game', player_id NULL) and player
-- props (scope='prop'). Append-only — never updated or deleted by the pull path. (A
-- retention sweep can prune old captured_at later; not needed until it grows.)
CREATE TABLE IF NOT EXISTS odds_snapshots (
    id             bigserial   PRIMARY KEY,
    captured_at    timestamptz NOT NULL,
    game_id        bigint      NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    scope          varchar(8)  NOT NULL,   -- 'game' | 'prop'
    player_id      integer     REFERENCES players(id),
    market         varchar(20) NOT NULL,
    side           varchar(10) NOT NULL,
    line           numeric(5,2),
    bookmaker      varchar(40) NOT NULL,
    price_american integer     NOT NULL,
    price_decimal  numeric(7,3) NOT NULL
);

-- Lookup pattern: the movement of one selection across a book over time.
CREATE INDEX IF NOT EXISTS idx_odds_snap_selection
    ON odds_snapshots (game_id, scope, player_id, market, side, line, bookmaker, captured_at);
