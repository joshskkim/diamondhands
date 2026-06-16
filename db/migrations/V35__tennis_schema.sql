-- Diamond — Tennis (ATP) schema
-- =============================================================================
-- First non-baseball sport. Tennis is individual + surface-based, so there are
-- no teams/stadiums/pitchers here. Data comes from the Tennismylife/TML-Database
-- (a maintained, Sackmann-schema ATP dataset); player ids are official ATP player
-- codes (e.g. 'D643', 'N409'). Holds historical data for training + backtesting
-- in Milestone 1; the live slate is layered on later.

-- Players (derived from TML match rows; enriched from ATP_Database.csv later)
CREATE TABLE tennis_players (
    id           VARCHAR(12) PRIMARY KEY,    -- ATP player code (TML winner_id/loser_id)
    full_name    VARCHAR(100) NOT NULL,
    hand         CHAR(1),                    -- 'R' / 'L' / 'U' (unknown)
    backhand     SMALLINT,                   -- 1 = one-handed, 2 = two-handed (nullable; future style lever)
    birth_date   DATE,
    country      VARCHAR(3),                 -- IOC country code
    height_cm    INT,
    current_rank INT,
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- Tournaments (derived from TML match rows; tourney_id is a string like "2024-339")
CREATE TABLE tennis_tournaments (
    id                VARCHAR(60) PRIMARY KEY,   -- TML tourney_id (Davis Cup codes run long)
    name              VARCHAR(120) NOT NULL,
    surface           VARCHAR(10),               -- hard / clay / grass / carpet
    indoor            BOOLEAN,                   -- nullable
    level             VARCHAR(10),               -- tourney_level: 250/500/1000/G/M/A/D/F/C...
    best_of           SMALLINT,                  -- 3 or 5
    draw_size         INT,
    location          VARCHAR(100),
    start_date        DATE,
    -- Finer than the surface bucket; populated later (Milestone 3 court-speed lever).
    court_speed_index NUMERIC(4,3)
);

-- Matches — historical (winner known) and, later, the live slate (winner_id NULL).
-- player_a / player_b assignment is RANDOMIZED at load time so the slot carries
-- no information about the result (avoids positional label leakage in backtest).
CREATE TABLE tennis_matches (
    id           BIGSERIAL PRIMARY KEY,
    tourney_id   VARCHAR(60) REFERENCES tennis_tournaments(id),
    match_num    INT,
    round        VARCHAR(10),                -- R128/R64/.../QF/SF/F
    match_date   DATE NOT NULL,
    surface      VARCHAR(10),
    best_of      SMALLINT,
    player_a_id  VARCHAR(12) REFERENCES tennis_players(id),
    player_b_id  VARCHAR(12) REFERENCES tennis_players(id),
    winner_id    VARCHAR(12) REFERENCES tennis_players(id),  -- NULL until played; equals a or b
    -- ATP rank of each player at match time (from TML) — the backtest's ranking-favorite baseline.
    player_a_rank INT,
    player_b_rank INT,
    score        VARCHAR(60),                -- e.g. "6-4 7-6(3)"; "RET"/"W/O" flagged via status
    status       VARCHAR(20) DEFAULT 'completed',     -- completed / retired / walkover / scheduled
    UNIQUE (tourney_id, match_num)
);

CREATE INDEX idx_tennis_matches_date ON tennis_matches(match_date);
CREATE INDEX idx_tennis_matches_a ON tennis_matches(player_a_id, match_date DESC);
CREATE INDEX idx_tennis_matches_b ON tennis_matches(player_b_id, match_date DESC);

-- Per-player-per-match serve lines (Sackmann w_*/l_* columns). Return stats are
-- derived from the opponent's serve line. The analogue of MLB player_game_stats;
-- fuel for surface-specific SPW/RPW skill aggregation. Walkover/retired matches
-- are excluded from this table (not a clean performance signal).
CREATE TABLE tennis_player_match_stats (
    match_id        BIGINT REFERENCES tennis_matches(id) ON DELETE CASCADE,
    player_id       VARCHAR(12) REFERENCES tennis_players(id),
    is_winner       BOOLEAN NOT NULL,
    aces            INT,
    double_faults   INT,
    serve_points    INT,        -- svpt
    first_in        INT,        -- 1st serves in
    first_won       INT,        -- 1st-serve points won
    second_won      INT,        -- 2nd-serve points won
    serve_games     INT,        -- service games played
    bp_saved        INT,
    bp_faced        INT,
    PRIMARY KEY (match_id, player_id)
);

-- Rating snapshots. One row per (player, as_of_date, surface). surface = 'all'
-- holds the overall (surface-agnostic) Elo + skills; 'hard'/'clay'/'grass' hold
-- the surface-specific values. The match model blends the surface row with 'all'.
CREATE TABLE tennis_player_ratings (
    player_id     VARCHAR(12) REFERENCES tennis_players(id),
    as_of_date    DATE NOT NULL,
    surface       VARCHAR(10) NOT NULL,       -- 'all' / 'hard' / 'clay' / 'grass'
    elo           NUMERIC(7,2),
    serve_skill   NUMERIC(5,4),               -- recency-weighted serve points won (SPW)
    return_skill  NUMERIC(5,4),               -- recency-weighted return points won (RPW)
    matches_count INT,
    updated_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (player_id, as_of_date, surface)
);

CREATE INDEX idx_tennis_ratings_latest ON tennis_player_ratings(as_of_date DESC, surface);

-- Per-match model output (what the API will serve in Milestone 2).
CREATE TABLE tennis_match_projections (
    match_id           BIGINT PRIMARY KEY REFERENCES tennis_matches(id) ON DELETE CASCADE,
    player_a_id        VARCHAR(12) REFERENCES tennis_players(id),
    player_b_id        VARCHAR(12) REFERENCES tennis_players(id),
    p_win_a            NUMERIC(5,4),           -- P(player_a wins the match)
    p_serve_a          NUMERIC(5,4),           -- per-point serve win prob, A serving
    p_serve_b          NUMERIC(5,4),
    exp_total_games    NUMERIC(5,2),
    prob_straight_sets NUMERIC(5,4),           -- P(match ends in straight sets, either player)
    reasoning          JSONB,                  -- audit trail (elo split, skill inputs, blend)
    model_version      VARCHAR(20),
    projected_at       TIMESTAMPTZ DEFAULT NOW()
);
