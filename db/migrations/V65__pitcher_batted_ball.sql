-- Pitcher contact-quality allowed (Lever 1 — symmetric pitcher version of the
-- v2.9 batter barrel work in V21__batter_batted_ball.sql).
-- ============================================================================
-- Aggregated from pitch-level Statcast (launch_speed, bb_type, launch_speed_angle)
-- by `refresh-batted-ball`, split by the batter's stand faced ('L'/'R') so it
-- aligns with pitcher_skill's handedness shape. These are the pitcher-side
-- contact-quality-allowed inputs an HR model wants: how hard / how often the
-- pitcher gets barreled and how many fly balls he allows. Realized HR-allowed
-- (pitcher_skill.hr_per_pa) stabilises slowly; barrel%-allowed stabilises faster
-- and is the canonical pitcher HR signal — mirrors batter_batted_ball.barrel_pct.
-- No spray columns here: park-fit personalization is a batter-side concern.

CREATE TABLE pitcher_batted_ball (
    player_id     INT     NOT NULL REFERENCES players(id),
    season        INT     NOT NULL,
    vs_handedness CHAR(1) NOT NULL,           -- batter stand faced: 'L' or 'R'
    bip           INT     NOT NULL,           -- balls in play (sample size)
    fb_pct        NUMERIC(5,4),               -- fly balls / BIP
    hard_hit_pct  NUMERIC(5,4),               -- EV >= 95 mph
    barrel_pct    NUMERIC(5,4),               -- Statcast barrels / BIP
    updated_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (player_id, season, vs_handedness)
);

CREATE INDEX idx_pitcher_batted_ball_season ON pitcher_batted_ball(season);

-- Prior-season EB-regressed barrel-allowed (per pitcher×hand), attached during
-- refresh-skills as the true-talent HR signal blended into the pitcher.hr
-- multiplier. NULL until the prior season's pitcher_batted_ball is populated, in
-- which case the model falls back to the pre-Lever-1 realized-HR basis.
ALTER TABLE pitcher_skill ADD COLUMN barrel_allowed NUMERIC(5,4);

-- Mirror onto the point-in-time snapshot table the backtest reads
-- (runner._load_pitcher_splits_snapshot), so the A/B actually exercises the blend.
-- barrel_allowed is prior-season (constant across a season's Monday snapshots), so
-- refresh-skill-snapshots attaches the same value to every snapshot for the season.
ALTER TABLE pitcher_skill_snapshots ADD COLUMN barrel_allowed NUMERIC(5,4);
