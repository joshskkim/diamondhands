-- Mirror the matchup audit columns onto backtest_projections (v2.1).
-- Now that the pitch-mix matchup drives the projection, the backtest writes the
-- matchup xwOBA and quality it used, so a run can be audited the same way the live
-- batter_projections table is (and so `project --as-of` rows are inspectable).
ALTER TABLE backtest_projections ADD COLUMN matchup_xwoba   NUMERIC(5,4);
ALTER TABLE backtest_projections ADD COLUMN matchup_quality VARCHAR(20);
