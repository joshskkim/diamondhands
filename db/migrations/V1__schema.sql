-- Diamond MLB Projection App — initial schema
-- =============================================================================

-- Reference data

CREATE TABLE teams (
    id            INT PRIMARY KEY,           -- MLB team ID (MLBAM)
    abbreviation  VARCHAR(5)   NOT NULL,
    name          VARCHAR(100) NOT NULL,
    home_stadium_id INT                      -- FK set after stadiums populated
);

CREATE TABLE stadiums (
    id               INT PRIMARY KEY,
    name             VARCHAR(100) NOT NULL,
    team_id          INT REFERENCES teams(id),
    city             VARCHAR(50),
    latitude         NUMERIC(9,6)  NOT NULL,
    longitude        NUMERIC(9,6)  NOT NULL,
    is_dome          BOOLEAN       NOT NULL,
    is_retractable   BOOLEAN       DEFAULT FALSE,
    -- Orientation: compass bearing in degrees from home plate to center field.
    -- 0=North, 90=East, 180=South, 270=West.
    cf_bearing_degrees INT         NOT NULL,
    -- Park factors (1.00 = league average).
    -- Source: Statcast 3-year rolling park factor averages (Baseball Savant).
    park_factor_hits   NUMERIC(4,3) DEFAULT 1.000,
    park_factor_hr_lhb NUMERIC(4,3) DEFAULT 1.000,
    park_factor_hr_rhb NUMERIC(4,3) DEFAULT 1.000
);

CREATE TABLE players (
    id          INT PRIMARY KEY,             -- MLBAM ID
    full_name   VARCHAR(100) NOT NULL,
    team_id     INT REFERENCES teams(id),
    position    VARCHAR(10),
    bats        CHAR(1),                     -- L/R/S
    throws      CHAR(1),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Aggregated season-level batter skill (recomputed nightly)
CREATE TABLE batter_skill (
    player_id        INT PRIMARY KEY REFERENCES players(id),
    season           INT NOT NULL,
    plate_appearances INT NOT NULL,
    -- Statcast / advanced
    xwoba            NUMERIC(5,4),
    woba             NUMERIC(5,4),
    k_rate           NUMERIC(5,4),
    bb_rate          NUMERIC(5,4),
    iso              NUMERIC(5,4),
    babip            NUMERIC(5,4),
    barrel_rate      NUMERIC(5,4),
    hard_hit_rate    NUMERIC(5,4),
    -- Last-30-days versions for recency weighting
    xwoba_l30        NUMERIC(5,4),
    k_rate_l30       NUMERIC(5,4),
    iso_l30          NUMERIC(5,4),
    pa_l30           INT,
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

-- Aggregated pitcher skill, split by batter handedness
CREATE TABLE pitcher_skill (
    player_id      INT    NOT NULL REFERENCES players(id),
    season         INT    NOT NULL,
    vs_handedness  CHAR(1) NOT NULL,         -- 'L' or 'R'
    batters_faced  INT    NOT NULL,
    woba_against   NUMERIC(5,4),
    xwoba_against  NUMERIC(5,4),
    k_rate         NUMERIC(5,4),
    bb_rate        NUMERIC(5,4),
    hr_per_pa      NUMERIC(5,4),
    hits_per_pa    NUMERIC(5,4),
    updated_at     TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (player_id, season, vs_handedness)
);

-- Today's slate
CREATE TABLE games (
    id                          BIGINT PRIMARY KEY,
    game_date                   DATE    NOT NULL,
    home_team_id                INT REFERENCES teams(id),
    away_team_id                INT REFERENCES teams(id),
    stadium_id                  INT REFERENCES stadiums(id),
    start_time_utc              TIMESTAMPTZ NOT NULL,
    status                      VARCHAR(20),
    home_probable_pitcher_id    INT REFERENCES players(id),
    away_probable_pitcher_id    INT REFERENCES players(id),
    -- Weather snapshot at projection time
    temperature_f               INT,
    wind_speed_mph              INT,
    wind_direction_degrees      INT,         -- 0-359, meteorological "from" direction
    weather_fetched_at          TIMESTAMPTZ,
    -- Projection metadata
    projected_at                TIMESTAMPTZ,
    UNIQUE (game_date, home_team_id, away_team_id)
);

CREATE INDEX idx_games_date ON games(game_date);

-- Per-game per-batter projections (what the API serves)
CREATE TABLE batter_projections (
    game_id              BIGINT REFERENCES games(id) ON DELETE CASCADE,
    player_id            INT REFERENCES players(id),
    opposing_pitcher_id  INT REFERENCES players(id),
    is_home              BOOLEAN NOT NULL,
    expected_pa          NUMERIC(4,2),
    -- Probabilities (0.0 – 1.0)
    p_hit_1plus          NUMERIC(5,4),
    p_hit_2plus          NUMERIC(5,4),
    p_hr                 NUMERIC(5,4),
    p_k_1plus            NUMERIC(5,4),
    -- Expected counts
    expected_hits        NUMERIC(4,3),
    expected_total_bases NUMERIC(4,3),
    -- Adjustment audit trail (for debugging / UI explanation)
    adj_park             NUMERIC(4,3),
    adj_pitcher          NUMERIC(4,3),
    adj_weather_hr       NUMERIC(4,3),
    adj_weather_hits     NUMERIC(4,3),
    computed_at          TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (game_id, player_id)
);

CREATE INDEX idx_bp_game ON batter_projections(game_id);

-- Per-game team-level projections
CREATE TABLE game_projections (
    game_id              BIGINT PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
    expected_home_runs   NUMERIC(4,2),
    expected_away_runs   NUMERIC(4,2),
    expected_total_runs  NUMERIC(4,2),
    computed_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Historical game logs (fuel for batter_skill / pitcher_skill aggregation)
CREATE TABLE player_game_stats (
    player_id          INT REFERENCES players(id),
    game_date          DATE    NOT NULL,
    game_id            BIGINT,
    opponent_team_id   INT REFERENCES teams(id),
    is_home            BOOLEAN NOT NULL,
    -- Hitting
    plate_appearances  INT,
    at_bats            INT,
    hits               INT,
    home_runs          INT,
    total_bases        INT,
    strikeouts         INT,
    walks              INT,
    -- Statcast contact quality
    xwoba              NUMERIC(5,4),
    woba               NUMERIC(5,4),
    -- Pitching (for pitcher_skill aggregation; NOT for pitcher props)
    batters_faced      INT,
    pitcher_strikeouts INT,
    hits_allowed       INT,
    hr_allowed         INT,
    PRIMARY KEY (player_id, game_date, game_id)
);

CREATE INDEX idx_pgs_player_date ON player_game_stats(player_id, game_date DESC);
