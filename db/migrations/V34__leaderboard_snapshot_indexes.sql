-- Indexes matching the DISTINCT ON snapshot resolution used by the pitch-type leaderboard
-- (and the batched projection/prop queries): latest (season, as_of_date) per
-- (player_id, vs_handedness). Without these the DISTINCT ON falls back to a full sort of
-- the snapshot tables; once they grew past ~500k rows that regressed the leaderboard query
-- to ~98s. With these indexes + restricting the snapshot CTEs to the slate's players the
-- query runs in ~70ms.

CREATE INDEX IF NOT EXISTS idx_arsenal_snapshot
    ON pitcher_arsenal (player_id, vs_handedness, as_of_date DESC, season DESC);

CREATE INDEX IF NOT EXISTS idx_bpt_snapshot
    ON batter_pitch_type_stats (player_id, vs_handedness, as_of_date DESC, season DESC);
