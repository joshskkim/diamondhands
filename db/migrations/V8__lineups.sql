-- Confirmed lineups + batting order (v2.0 Sprint 1).
-- ============================================================================
-- The projection engine previously assumed a flat 4.0 PA for every starter
-- because batting order was unknown. With confirmed lineups we know each
-- batter's slot and can weight expected PA by lineup position.

-- When the *actual* (not projected) lineup for a side was first observed.
-- NULL = lineup not yet confirmed; projections fall back to the L30-PA proxy.
ALTER TABLE games ADD COLUMN home_lineup_confirmed_at TIMESTAMPTZ;
ALTER TABLE games ADD COLUMN away_lineup_confirmed_at TIMESTAMPTZ;

-- One row per confirmed batting-order slot (1-9) per side per game.
CREATE TABLE game_lineups (
    game_id       BIGINT  NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    is_home       BOOLEAN NOT NULL,
    batting_order INT     NOT NULL CHECK (batting_order BETWEEN 1 AND 9),
    player_id     INT     REFERENCES players(id),
    PRIMARY KEY (game_id, is_home, batting_order)
);

-- Lineup metadata on each projected batter row.
-- lineup_position: 1-9 when the lineup is confirmed, else NULL (projected lineup).
-- lineup_confirmed: TRUE when expected_pa was derived from a confirmed batting order.
ALTER TABLE batter_projections ADD COLUMN lineup_position  INT;
ALTER TABLE batter_projections ADD COLUMN lineup_confirmed BOOLEAN;
