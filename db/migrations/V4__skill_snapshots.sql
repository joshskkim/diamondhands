-- Point-in-time skill snapshots for honest backtesting (no data leakage).
-- Populated by: uv run python main.py refresh-skill-snapshots --season YYYY ...

CREATE TABLE batter_skill_snapshots (
    player_id         INT   NOT NULL,
    as_of_date        DATE  NOT NULL,
    season            INT   NOT NULL,
    plate_appearances INT   NOT NULL,
    xwoba             NUMERIC(5,4),
    woba              NUMERIC(5,4),
    k_rate            NUMERIC(5,4),
    bb_rate           NUMERIC(5,4),
    iso               NUMERIC(5,4),
    babip             NUMERIC(5,4),
    barrel_rate       NUMERIC(5,4),
    hard_hit_rate     NUMERIC(5,4),
    xwoba_l30         NUMERIC(5,4),
    k_rate_l30        NUMERIC(5,4),
    iso_l30           NUMERIC(5,4),
    pa_l30            INT,
    computed_at       TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (player_id, as_of_date)
);

CREATE TABLE pitcher_skill_snapshots (
    player_id     INT     NOT NULL,
    as_of_date    DATE    NOT NULL,
    season        INT     NOT NULL,
    vs_handedness CHAR(1) NOT NULL,
    batters_faced INT     NOT NULL,
    woba_against  NUMERIC(5,4),
    xwoba_against NUMERIC(5,4),
    k_rate        NUMERIC(5,4),
    bb_rate       NUMERIC(5,4),
    hr_per_pa     NUMERIC(5,4),
    hits_per_pa   NUMERIC(5,4),
    computed_at   TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (player_id, as_of_date, vs_handedness)
);

CREATE INDEX idx_bss_date ON batter_skill_snapshots(as_of_date);
CREATE INDEX idx_pss_date ON pitcher_skill_snapshots(as_of_date);
