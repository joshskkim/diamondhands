-- Walks prop: P(>=1 walk) per batter projection.
-- ============================================================================
-- v2.11 projects a per-batter walk probability from batter_skill.bb_rate × the
-- opposing pitcher's walk-allowed multiplier (no park/weather term — walks are
-- plate discipline, not aerodynamics). Feeds the model-first "Walk" prop card,
-- mirroring p_k_1plus. Nullable: rows projected before this column existed (or by
-- the league-average lineup pad) simply have no walk probability.

ALTER TABLE batter_projections
    ADD COLUMN p_bb_1plus NUMERIC(5,4);
