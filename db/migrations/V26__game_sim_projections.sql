-- Monte-Carlo game-simulator outputs per game (BallparkPal-style unified sim).
-- ============================================================================
-- One row per game holding distributional outputs derived from a single N-sim run
-- of game_sim.py: full-game runs/win-prob, first-five-innings (F5) markets, and
-- first-inning (F1 / NRFI-YRFI). The *_total_hist arrays are histograms of combined
-- runs (bins 0..N, last bin = >=N) so the API can compute P(over any line) and the
-- edge vs a book total without re-simulating. F5 is the engine's most rigorous output
-- (our batter rates are starter-adjusted and the early innings are starter-dominated);
-- the full game faces a bullpen transition after the 5th inning.

CREATE TABLE game_sim_projections (
    game_id              BIGINT PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
    n_sims               INTEGER     NOT NULL,

    -- Full game (9 innings, starter -> bullpen after the 5th)
    expected_home_runs   NUMERIC(4,2),
    expected_away_runs   NUMERIC(4,2),
    expected_total       NUMERIC(4,2),
    p_home_win           NUMERIC(4,3),          -- extra-inning ties split as a coin flip
    total_hist           INTEGER[],             -- combined-run histogram, bins 0..25

    -- First five innings (F5)
    f5_expected_home     NUMERIC(4,2),
    f5_expected_away     NUMERIC(4,2),
    f5_expected_total    NUMERIC(4,2),
    f5_p_home_lead       NUMERIC(4,3),          -- F5 moneyline (home leads after 5)
    f5_p_away_lead       NUMERIC(4,3),
    f5_p_tie             NUMERIC(4,3),          -- F5 push
    f5_total_hist        INTEGER[],             -- combined-run histogram, bins 0..15

    -- First inning (F1 / NRFI-YRFI)
    p_yrfi               NUMERIC(4,3),          -- P(>=1 run in the 1st)

    computed_at          TIMESTAMPTZ DEFAULT NOW()
);
