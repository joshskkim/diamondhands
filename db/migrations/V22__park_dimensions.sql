-- Park outfield dimensions (foundation for batted-ball / trajectory HR modeling).
-- ============================================================================
-- Foul-line + center-field distances (ft) and outfield wall heights (ft) per park.
-- Distances are cross-referenced from reliable sources and corrected against known
-- errors in consumer tables (e.g. Kauffman lines 330 not 387; Oracle RF 309).
-- They carry a few feet of uncertainty and may shift when parks are reconfigured.
-- Wall heights are populated only where well-documented (Fenway 37, PNC RF 21,
-- Oracle RF ~25, Crawford boxes, etc.); standard ~8 ft elsewhere.
--
-- Power-alley (LCF/RCF) distances are intentionally omitted: they are not reliably
-- sourceable for all 30 parks. A later batter-specific park factor interpolates the
-- fence distance by spray angle from these line + CF points.

ALTER TABLE stadiums ADD COLUMN lf_line_ft  INT;   -- left-field foul line distance
ALTER TABLE stadiums ADD COLUMN cf_ft       INT;   -- center-field distance
ALTER TABLE stadiums ADD COLUMN rf_line_ft  INT;   -- right-field foul line distance
ALTER TABLE stadiums ADD COLUMN lf_wall_ft  INT;   -- left-field wall height
ALTER TABLE stadiums ADD COLUMN cf_wall_ft  INT;   -- center-field wall height
ALTER TABLE stadiums ADD COLUMN rf_wall_ft  INT;   -- right-field wall height
