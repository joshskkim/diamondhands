-- Per-start pitcher workload lines, from MLB Stats API boxscores.
--
-- player_game_stats has pitcher K/BF but no OUTS/innings — and outs are the spine of
-- every starter prop (recorded outs = the market; Ks and ER are rates × how deep he
-- goes) plus the game sim's starter→bullpen transition. One row per START (relievers
-- excluded; gamesStarted=1 in the boxscore). Populated by backfill-pitcher-starts.
CREATE TABLE IF NOT EXISTS pitcher_starts (
    player_id   integer NOT NULL REFERENCES players(id),
    game_id     bigint  NOT NULL REFERENCES games(id),
    game_date   date    NOT NULL,
    team_id     integer REFERENCES teams(id),
    opponent_id integer REFERENCES teams(id),
    is_home     boolean,
    outs        integer NOT NULL,      -- outs recorded (innings*3)
    batters_faced integer,
    strikeouts  integer,
    walks       integer,
    hits_allowed integer,
    hr_allowed  integer,
    earned_runs integer,
    pitches     integer,
    PRIMARY KEY (player_id, game_id)
);

CREATE INDEX IF NOT EXISTS idx_pitcher_starts_player_date
    ON pitcher_starts (player_id, game_date DESC);
CREATE INDEX IF NOT EXISTS idx_pitcher_starts_date
    ON pitcher_starts (game_date);
