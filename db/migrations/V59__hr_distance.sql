-- Per-batter home-run distance, powering the "longest-HR upside" tiebreaker on HR picks
-- (a Fanatics boost pays extra if your HR pick also hits the day's longest HR). Note
-- batter_spray_bins.avg_distance_ft averages ALL balls in play; this is HR-only — how far
-- a player's home runs actually travel: the average and the 90th percentile (his tail power,
-- which is what decides "longest of the day").
CREATE TABLE IF NOT EXISTS batter_hr_distance (
    player_id        INT NOT NULL REFERENCES players(id),
    season           INT NOT NULL,
    hr_n             INT NOT NULL,
    avg_distance_ft  NUMERIC(5,1),
    p90_distance_ft  NUMERIC(5,1),
    updated_at       TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (player_id, season)
);

-- Projected HR carry for this game = the batter's shrunk HR distance + today's park/weather
-- carry delta (feet, already computed by the projection's d_carry). The long-ball-upside axis
-- shown on HR prop cards; NULL when the batter has no measured HR-distance sample.
ALTER TABLE batter_projections
    ADD COLUMN IF NOT EXISTS hr_distance_ft NUMERIC(5,1);
