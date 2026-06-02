-- Pitch-mix matchup audit columns on batter_projections (v2.1 Sprint 2).
-- matchup_xwoba: the usage-weighted, pitch-type-regressed xwOBA that replaced the
--   flat season blend as the hit-rate driver (the K rate and ISO get the same
--   treatment internally, but xwOBA is the headline number surfaced in the UI).
-- matchup_quality: 'matchup' when the opposing pitcher had enough arsenal data to
--   build a real matchup, 'fallback_overall' when it fell back to v2.0.0 behavior.
ALTER TABLE batter_projections ADD COLUMN matchup_xwoba   NUMERIC(5,4);
ALTER TABLE batter_projections ADD COLUMN matchup_quality VARCHAR(20);
