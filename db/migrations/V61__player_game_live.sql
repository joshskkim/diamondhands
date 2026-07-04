-- Live (in-progress) per-player box-score lines, for the prop board's real-time count
-- trackers. Deliberately SEPARATE from player_game_stats / pitcher_starts so the live
-- boxscore writes never touch the Final-graded tables (or their COALESCE/Statcast logic).
-- Throwaway: overwritten each `live-refresh` tick and irrelevant once a game is Final
-- (the Final tables take over). One row per (player, game); a two-way player carries both
-- the batting and pitching columns, merged by two column-scoped upserts.
CREATE TABLE IF NOT EXISTS player_game_live (
    player_id          INT    NOT NULL,
    game_id            BIGINT NOT NULL,
    game_date          DATE,
    -- batter
    plate_appearances  INT,
    at_bats            INT,
    hits               INT,
    home_runs          INT,
    total_bases        INT,
    strikeouts         INT,
    walks              INT,
    -- pitcher (starter)
    outs               INT,
    batters_faced      INT,
    pitcher_strikeouts INT,
    hits_allowed       INT,
    earned_runs        INT,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (player_id, game_id)
);

CREATE INDEX IF NOT EXISTS idx_player_game_live_date ON player_game_live (game_date);
