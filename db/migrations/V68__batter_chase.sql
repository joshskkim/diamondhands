-- Batter chase (O-Swing) for the K anchor (Lever 3).
-- ============================================================================
-- The whiff-implied K anchor (v2.8, projection/prior.py:whiff_k_anchor) regresses
-- the K prior toward a batter's swing-and-miss rate. An OOS check (2024→2025, n=236)
-- showed chase rate (swings at out-of-zone pitches) adds INCREMENTAL K signal
-- because it's nearly orthogonal to whiff (corr .13) — unlike CSW, which is mostly
-- redundant with whiff (.64) and is therefore NOT stored. chase_rate is gated into
-- the anchor behind DIAMOND_CHASE_K_ENABLED. Populated by refresh-pitch-aggregations.
--
-- oz_pitches (out-of-zone pitches seen of this type) is the weight for aggregating
-- the per-pitch-type chase_rate to an overall batter chase in refresh-priors.
ALTER TABLE batter_pitch_type_stats ADD COLUMN chase_rate NUMERIC(5,4);
ALTER TABLE batter_pitch_type_stats ADD COLUMN oz_pitches INT;
