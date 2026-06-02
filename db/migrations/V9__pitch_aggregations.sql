-- Pitch-mix matchup model (v2.1 Sprint 2).
-- ============================================================================
-- Per-batter xwOBA/K/ISO split by pitch type, per-pitcher arsenal usage, and
-- league baselines per pitch type. The projection engine weights a batter's
-- per-pitch-type skill by the opposing pitcher's usage of each pitch to build a
-- matchup-aware xwOBA / K rate / ISO that replaces the flat season blend.
--
-- Pitch types are normalized to 7 buckets in statcast_pitch.normalize_pitch_type:
--   FF (4-seam), SI (sinker), FC (cutter), SL (slider/sweeper),
--   CU (curve/knuckle-curve), CH (changeup), FS (splitter).
--
-- as_of_date is part of the PK, so these tables double as point-in-time
-- snapshots: the live refresh writes one as_of_date (today); the snapshot
-- backfill writes one per Monday. Both the prod and backtest projection paths
-- read the most recent row with as_of_date <= the reference date.

-- Batter outcomes by pitch type and opposing-pitcher handedness.
-- xwoba/k_rate/iso/hr_rate are RAW (unregressed) season-to-date rates; empirical
-- Bayes regression toward the league baseline is applied at query time in the
-- projection, so the stored data stays reusable if K changes.
CREATE TABLE batter_pitch_type_stats (
    player_id        INT         NOT NULL REFERENCES players(id),
    season           INT         NOT NULL,
    as_of_date       DATE        NOT NULL,
    pitch_type       VARCHAR(5)  NOT NULL,
    vs_handedness    CHAR(1)     NOT NULL,  -- opposing pitcher's throws: 'L', 'R', or 'A' (any)
    -- Sample
    pitches_seen     INT         NOT NULL,
    pa_ended_on_type INT         NOT NULL,  -- PAs that ended on this pitch type
    -- Outcomes (on PAs ended on this type, except swing/whiff which are per-pitch)
    xwoba            NUMERIC(5,4),
    woba             NUMERIC(5,4),
    k_rate           NUMERIC(5,4),
    iso              NUMERIC(5,4),  -- (TB - H) / AB on PAs ended on this type
    hr_rate          NUMERIC(5,4),  -- HR / PAs ended on this type
    swing_rate       NUMERIC(5,4),  -- swings / pitches_seen
    whiff_rate       NUMERIC(5,4),  -- swinging strikes / swings
    PRIMARY KEY (player_id, season, as_of_date, pitch_type, vs_handedness)
);

CREATE INDEX idx_bpt_player_date ON batter_pitch_type_stats(player_id, as_of_date);

-- Pitcher arsenal: usage and results by pitch type vs batter handedness.
CREATE TABLE pitcher_arsenal (
    player_id      INT         NOT NULL REFERENCES players(id),
    season         INT         NOT NULL,
    as_of_date     DATE        NOT NULL,
    pitch_type     VARCHAR(5)  NOT NULL,
    vs_handedness  CHAR(1)     NOT NULL,  -- batters' stand: 'L', 'R', or 'A' (any)
    -- Usage
    pitches_thrown INT         NOT NULL,
    usage_rate     NUMERIC(5,4),  -- pitches_thrown / total pitches vs that hand
    -- Performance
    xwoba_against  NUMERIC(5,4),
    whiff_rate     NUMERIC(5,4),
    avg_velocity   NUMERIC(4,1),
    PRIMARY KEY (player_id, season, as_of_date, pitch_type, vs_handedness)
);

CREATE INDEX idx_arsenal_player_date ON pitcher_arsenal(player_id, as_of_date);

-- League baselines per pitch type, used as the regression target at query time
-- and as the comparison point for the "edge" surfaced in the UI / leaderboards.
-- Season-level (no as_of_date): league means are stable enough that using the
-- final-season baseline for mid-season snapshots is a negligible leak.
CREATE TABLE pitch_type_league_baselines (
    season            INT         NOT NULL,
    pitch_type        VARCHAR(5)  NOT NULL,
    vs_handedness     CHAR(1)     NOT NULL,
    league_xwoba      NUMERIC(5,4),
    league_iso        NUMERIC(5,4),
    league_k_rate     NUMERIC(5,4),
    league_usage_rate NUMERIC(5,4),
    PRIMARY KEY (season, pitch_type, vs_handedness)
);
