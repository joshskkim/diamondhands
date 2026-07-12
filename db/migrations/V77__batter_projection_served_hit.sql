-- Served (blended) hit probability, alongside the raw model prob.
--
-- The batter HIT market is regressed toward the player's demonstrated season clear rate
-- (empirical shrinkage — see projection/prop_blend.py, ported from the API's PropBlend).
-- A held-out backtest showed this blend beats the raw model AND beats the isotonic
-- calibrator, so for hit it REPLACES calibration: served = blend(raw model), and p_hit_1plus
-- stays the RAW (uncalibrated) hit prob. Kept in a separate column so raw is still available
-- to model training / the calibration fit / audit, while odds, picks, accuracy, and the
-- game-page batter table read the served value. NULL when the raw prob is the degenerate
-- 0/1 sentinel (0-PA / padded slot) — those are never blended.
ALTER TABLE batter_projections
    ADD COLUMN IF NOT EXISTS p_hit_1plus_served NUMERIC(5,4);

ALTER TABLE backtest_projections
    ADD COLUMN IF NOT EXISTS p_hit_1plus_served NUMERIC(5,4);
