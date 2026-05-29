-- Add pitcher data quality tier tag to batter_projections
ALTER TABLE batter_projections
    ADD COLUMN pitcher_data_quality VARCHAR(20)
        CHECK (pitcher_data_quality IN ('matchup', 'overall', 'league_avg'));
