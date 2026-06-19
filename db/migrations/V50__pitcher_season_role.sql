-- Season-level pitcher role stats (gamesStarted/gamesPitched/IP), fetched per probable
-- pitcher in daily-slate. Used by the opener detector to decide whether a listed
-- "starter" is actually a reliever used as an opener (skip projecting them as a starter).
CREATE TABLE IF NOT EXISTS pitcher_season_role (
    player_id        integer NOT NULL REFERENCES players(id),
    season           integer NOT NULL,
    games_started    integer,
    games_pitched    integer,
    innings_pitched  numeric(6,1),
    games_finished   integer,
    updated_at       timestamptz NOT NULL DEFAULT NOW(),
    PRIMARY KEY (player_id, season)
);
