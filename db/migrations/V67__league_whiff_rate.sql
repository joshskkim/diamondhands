-- League per-pitch-type whiff baseline (Lever 2).
-- ============================================================================
-- The matchup K rate (projection/matchup.py) is driven only by the BATTER's
-- per-pitch-type K rate weighted by the pitcher's usage — the pitcher's own
-- swing-and-miss ability is ignored, even though pitcher_arsenal.whiff_rate is
-- already aggregated. Lever 2 folds the pitcher's per-pitch whiff into the matchup
-- as a multiplier relative to the league whiff for each pitch type; this column is
-- that neutral point. Populated by refresh-pitch-aggregations (compute_league_baselines).
ALTER TABLE pitch_type_league_baselines ADD COLUMN league_whiff_rate NUMERIC(5,4);
