-- Opposing-team defense hit-suppression factor on each batter projection (audit + UI).
-- ============================================================================
-- The leak-free team-defense factor (actual non-HR hits / Σ xBA on in-park balls in play,
-- season-to-date, shrunk toward league average) that scaled this batter's non-HR hit rate.
-- 1.0 = neutral / feature off. Stored alongside the other adj_* multipliers so the prop
-- board can render a "opposing defense" reasoning bullet on the hit card.

ALTER TABLE batter_projections
    ADD COLUMN adj_defense NUMERIC(5,3) NOT NULL DEFAULT 1.0;
