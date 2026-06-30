-- Marcel-style multi-year true-talent prior per PITCHER (Lever 4 — the pitcher
-- analogue of V27 batter_projection_prior).
-- ============================================================================
-- refresh-pitcher-priors computes a projected per-PA baseline from each pitcher's
-- prior three seasons (recency weights 5/4/3, BF-weighted, regressed to league).
-- compute_pitcher_skill_rows then regresses the pitcher's in-season rates toward
-- THIS prior instead of the flat league mean, so a thin in-season sample reverts
-- to the pitcher's established skill. HR is regressed heavily toward league (two
-- OOS tests show pitcher HR-allowed wants the league anchor, not own-history —
-- DIPS; see memory pitcher-barrel-allowed-dead), so its prior ≈ league by design.
--
-- Unlike the batter prior (sourced from player_game_stats), this prior is sourced
-- straight from the Statcast cache per season — that carries BB-allowed (absent
-- from player_game_stats) and needs no multi-season game-log backfill.
--
-- `season` is the TARGET season the prior projects (a 2026 row is built from
-- 2023/2024/2025). `proj_bf` is the recency-weighted BF behind the prior (a
-- reliability proxy). `method` tags the source for future licensed projections.
CREATE TABLE IF NOT EXISTS pitcher_projection_prior (
    player_id        integer     NOT NULL REFERENCES players(id),
    season           integer     NOT NULL,
    proj_k_rate      numeric(5,4),
    proj_bb_rate     numeric(5,4),
    proj_hr_per_pa   numeric(5,4),
    proj_hits_per_pa numeric(5,4),
    proj_bf          integer,
    method           varchar(20) NOT NULL DEFAULT 'marcel',
    updated_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (player_id, season, method)
);
