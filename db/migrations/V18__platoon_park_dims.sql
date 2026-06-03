-- V18 — Batter platoon-split skill + park physical dimensions (data layer)
-- =============================================================================
-- Part of U5: surface the data a later projection unit will wire in.
--
-- 1. batter_platoon_skill: batter Statcast skill split by the OPPOSING PITCHER's
--    throwing hand (vs_hand ∈ {'L','R'}). Mirrors batter_skill column style and
--    pitcher_skill's split-table shape (one row per player×season×hand).
--    Switch hitters: Statcast `stand` already reflects the side actually batted
--    from, so the split is computed directly off the pitcher's `p_throws` with no
--    correction (see statcast.py module docstring).
--
-- 2. Park physical dimensions (LF/CF/RF distances, wall heights): NOT ADDED.
--    /data/stadiums.json contains only park factors, CF compass bearing,
--    lat/long, and dome/retractable flags — it carries NO outfield distances or
--    wall heights. Per the unit spec, we do not invent data, so the stadiums
--    table is left unchanged. If dimension fields are later added to the JSON,
--    a follow-up migration should add matching columns here.
-- =============================================================================

-- Aggregated season-level batter skill, split by opposing pitcher handedness.
CREATE TABLE batter_platoon_skill (
    player_id  INT     NOT NULL REFERENCES players(id),
    season     INT     NOT NULL,
    vs_hand    CHAR(1) NOT NULL,          -- opposing PITCHER throws 'L' or 'R'
    pa         INT     NOT NULL,
    -- Statcast / advanced rates (regressed toward league mean by sample size)
    xwoba      NUMERIC(5,4),
    k_rate     NUMERIC(5,4),
    iso        NUMERIC(5,4),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (player_id, season, vs_hand)
);

CREATE INDEX idx_bps_player_season ON batter_platoon_skill(player_id, season);
