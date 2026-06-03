-- Bullpen / relief-pitching skill, aggregated per team and split by batter handedness.
-- =============================================================================
-- One row per (team_id, season, vs_hand). A "relief" PA is any plate appearance
-- charged to a pitcher who was NOT that game-side's starting pitcher (the pitcher
-- who threw the first pitch of the side). Mirrors the rate-column style of
-- pitcher_skill (see V1). The run/score projection model is a later consumer.
--
-- Switch-hitter convention: Statcast `stand` already reflects the side the batter
-- actually hit from, so it is used directly for the handedness split (see statcast.py).

CREATE TABLE bullpen_skill (
    team_id      INT     NOT NULL REFERENCES teams(id),
    season       INT     NOT NULL,
    vs_hand      CHAR(1) NOT NULL,         -- 'L' or 'R' (batter handedness faced)
    bf           INT     NOT NULL,         -- relief batters faced vs this handedness
    hits_per_pa  NUMERIC(5,4),
    hr_per_pa    NUMERIC(5,4),
    k_rate       NUMERIC(5,4),
    updated_at   TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (team_id, season, vs_hand)
);
