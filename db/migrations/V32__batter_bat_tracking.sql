-- Per-batter bat-tracking aggregates (Statcast 2024+: bat speed / swing shape).
-- The newest public Statcast signal, previously sitting unused in the pitch cache.
-- Feeds the power (ISO) prior — the model's weakest validated component — and,
-- later, the whiff side of the K model. Populated by refresh-bat-tracking.
CREATE TABLE IF NOT EXISTS batter_bat_tracking (
    player_id        integer      NOT NULL REFERENCES players(id),
    season           integer      NOT NULL,
    swings           integer      NOT NULL,        -- swings with measured bat speed
    avg_bat_speed    numeric(5,2),                 -- mph
    fast_swing_rate  numeric(5,4),                 -- share of swings >= 75 mph
    avg_swing_length numeric(5,2),                 -- feet
    avg_attack_angle numeric(5,2),                 -- degrees
    updated_at       timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (player_id, season)
);
