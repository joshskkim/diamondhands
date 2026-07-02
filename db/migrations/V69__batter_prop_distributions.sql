-- Batter TB / H+R+RBI prop distributions + run-line dog-side cover prob.
-- ============================================================================
-- The prop board's batter cards move from 0.5 occurrence props (1+ hit, 1+ K) to
-- line-based markets: Total Bases and Hits+Runs+RBI. The game simulator now
-- attributes each scored run to the runner who scored and each RBI to the batter
-- who drove it in, giving per-batter TB and H+R+RBI distributions. Like the
-- pitcher hists (V45), tb_hist / hrr_hist are raw simulation counts
-- (sum == n_sims); the API computes P(over line) by summing bins above the
-- line. Bins are 0..10 with the last bin a >=10 catch-all.
ALTER TABLE game_sim_batter_props
    ADD COLUMN n_sims        INTEGER,        -- histogram denominator for P(over)
    ADD COLUMN expected_hrr  NUMERIC(4,2),   -- E[hits + runs scored + RBI]
    ADD COLUMN tb_hist       INTEGER[],      -- total-bases counts, bins 0..10
    ADD COLUMN hrr_hist      INTEGER[];      -- hits+runs+RBI counts, bins 0..10

-- The sim persists P(home covers -1.5) and P(away covers -1.5) — complements of
-- the OTHER team's +1.5, but only in one orientation: P(home +1.5) was never
-- stored, so the run-line board couldn't price the underdog side when the book
-- favorite is the away team. p_home_cover_plus15 completes the set
-- (P(away -1.5) = 1 - p_home_cover_plus15).
ALTER TABLE game_sim_projections
    ADD COLUMN p_home_cover_plus15 NUMERIC(4,3);

-- H+R+RBI grading and season clear-rates need runs scored and RBI, which the
-- Statcast aggregation path can't produce — only the MLB boxscore backfill
-- fills these (COALESCE upserts leave them NULL from other paths).
ALTER TABLE player_game_stats
    ADD COLUMN runs INT,
    ADD COLUMN rbi  INT;

-- Same pair on the live boxscore table for the prop board's in-game trackers.
ALTER TABLE player_game_live
    ADD COLUMN runs INT,
    ADD COLUMN rbi  INT;
