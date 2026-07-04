-- HR quick-win batted-ball features (xHR foundation, Phase 1).
-- ============================================================================
-- The season-mean columns in V21 wash out the distribution where HR signal
-- actually lives. These three add the SOTA HR discriminators that survive
-- aggregation, computed per batter by `refresh-batted-ball`:
--   pulled_air_pct = pulled fly balls / BIP  (~66% of HRs are pulled FBs)
--   sweet_spot_pct = launch angle in 8-32°   (the barrel launch-angle window)
--   p90_ev_fbld    = 90th-pctile exit velo on FB+LD (top-of-distribution power,
--                    not the average — null until >= 10 air balls in the season)

ALTER TABLE batter_batted_ball
    ADD COLUMN pulled_air_pct NUMERIC(5,4),   -- (pull & fly_ball) / BIP
    ADD COLUMN sweet_spot_pct NUMERIC(5,4),   -- launch_angle in [8, 32] / BIP
    ADD COLUMN p90_ev_fbld    NUMERIC(5,2);   -- mph, p90 EV on fly balls + line drives
