-- Per-batted-ball event corpus for the xHR model (Phase 2 training data).
-- ============================================================================
-- The aggregate tables (batter_batted_ball) collapse a season to means and throw
-- away the per-ball distribution where HR signal actually lives. This table keeps
-- ONE ROW PER BATTED BALL so a learned xHR model can be trained on P(HR | exit
-- velo, launch angle, spray, park). ~120k rows/season; rebuilt per season by the
-- extractor (delete-then-insert), so no natural unique key is enforced.
--
-- Crucially includes home runs even when the hit-coordinate is missing (they still
-- carry launch_speed/launch_angle) — spray_deg is simply NULL there and the trainer
-- handles it. Dropping no-coordinate rows would zero out the positive class.

CREATE TABLE batted_ball_events (
    id             BIGSERIAL PRIMARY KEY,
    season         INT     NOT NULL,
    player_id      INT     NOT NULL,       -- batter
    game_pk        INT,
    park           TEXT,                   -- home-team code (stadium proxy)
    launch_speed   NUMERIC(5,2),           -- mph
    launch_angle   NUMERIC(5,2),           -- degrees
    spray_deg      NUMERIC(6,2),           -- catcher's view; NULL when hc coords absent
    bb_type        TEXT,                   -- ground_ball / line_drive / fly_ball / popup
    estimated_woba NUMERIC(5,4),           -- Statcast xwOBA on contact
    hit_distance   INT,                    -- feet
    is_hr          BOOLEAN NOT NULL        -- the training target
);

CREATE INDEX idx_bbe_season           ON batted_ball_events(season);
CREATE INDEX idx_bbe_player_season    ON batted_ball_events(player_id, season);
