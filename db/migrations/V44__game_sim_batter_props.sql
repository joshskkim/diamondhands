-- Per-batter prop probabilities from the Monte-Carlo game simulator.
-- ============================================================================
-- The game_sim.py run already produces a BatterProps distribution for every lineup
-- slot (P(1+ hit), P(2+ hits), P(HR), P(1+ K), expected TB/hits) as a by-product of
-- the same simulation that yields game_sim_projections — but until now those per-batter
-- outputs were computed and discarded. This table persists them so the prop board can
-- blend the simulator's estimate (which captures lineup turnover and PA-count variance
-- — the starter -> bullpen transition and how often the bat actually comes up) against
-- the closed-form per-PA binomial in batter_projections.
--
-- One row per (game, player) projected on the slate. Cleared and rewritten alongside
-- batter_projections / game_sim_projections each nightly project run.

CREATE TABLE game_sim_batter_props (
    game_id        BIGINT  NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    player_id      INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,

    p_hit_1plus    NUMERIC(4,3),   -- P(1+ hit)   — pairs with batter_projections.p_hit_1plus
    p_hit_2plus    NUMERIC(4,3),   -- P(2+ hits)
    p_hr           NUMERIC(4,3),   -- P(1+ HR)
    p_k_1plus      NUMERIC(4,3),   -- P(1+ K)
    expected_tb    NUMERIC(4,2),
    expected_hits  NUMERIC(4,2),

    computed_at    TIMESTAMPTZ DEFAULT NOW(),

    PRIMARY KEY (game_id, player_id)
);
