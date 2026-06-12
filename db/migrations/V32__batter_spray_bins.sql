-- Per-batter spray-direction bins for the hot-zone visual. The batted-ball profile
-- aggregation collapses hit coordinates to pull/center/oppo; this keeps the direction
-- at 10° granularity instead: 9 sectors spanning fair territory, FIELD-absolute
-- (bin 0 hugs the LF line, bin 8 the RF line) — clients mirror by handedness.
CREATE TABLE IF NOT EXISTS batter_spray_bins (
    player_id        INT NOT NULL REFERENCES players(id),
    season           INT NOT NULL,
    bin              SMALLINT NOT NULL CHECK (bin BETWEEN 0 AND 8),
    bip              INT NOT NULL,
    hr               INT NOT NULL DEFAULT 0,
    avg_distance_ft  NUMERIC(5,1),
    updated_at       TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (player_id, season, bin)
);
