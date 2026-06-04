-- Batter batted-ball / spray profile (BallparkPal-style batter physics inputs).
-- ============================================================================
-- Aggregated from pitch-level Statcast (launch_speed, launch_angle, hc_x/hc_y,
-- bb_type) by `refresh-batted-ball`. These are the batter-side inputs a park /
-- batted-ball model needs: where a hitter sprays the ball (pull/center/oppo),
-- his batted-ball mix (GB/LD/FB/PU), and contact quality (EV, hard-hit, barrel).
--
-- spray classification (catcher's view, handedness-adjusted):
--   pull   = LHB to RF / RHB to LF
--   center = within the center band
--   oppo   = LHB to LF / RHB to RF
-- A pull-heavy fly-ball hitter benefits most from a short pull-side porch — the
-- signal a later batter-specific park factor will consume.

CREATE TABLE batter_batted_ball (
    player_id          INT     NOT NULL REFERENCES players(id),
    season             INT     NOT NULL,
    bip                INT     NOT NULL,           -- balls in play (sample size)
    pull_pct           NUMERIC(5,4),
    center_pct         NUMERIC(5,4),
    oppo_pct           NUMERIC(5,4),
    gb_pct             NUMERIC(5,4),
    ld_pct             NUMERIC(5,4),
    fb_pct             NUMERIC(5,4),
    pu_pct             NUMERIC(5,4),               -- popups
    avg_launch_speed   NUMERIC(5,2),               -- mph
    avg_launch_angle   NUMERIC(5,2),               -- degrees
    hard_hit_pct       NUMERIC(5,4),               -- EV >= 95 mph
    barrel_pct         NUMERIC(5,4),               -- Statcast barrels / BIP
    updated_at         TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (player_id, season)
);

CREATE INDEX idx_batter_batted_ball_season ON batter_batted_ball(season);
