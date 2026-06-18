-- Starting-pitcher prop distributions from the Monte-Carlo game simulator.
-- ============================================================================
-- The game_sim.py run already simulates the opposing lineup's hits and runs against
-- each starter; we now snapshot the cumulative team hits/runs at the starter's projected
-- exit inning to get his hits-allowed and earned-runs distributions. (Earned runs are
-- approximated by total runs — the sim has no error model, a small conservative bias.)
-- This table persists those distributions so the prop board can serve pitcher
-- hits-allowed / earned-runs markets the same way it serves Ks and outs.
--
-- One row per (game, starting pitcher) on the slate, rewritten each nightly project run.
-- hits_hist / er_hist are raw simulation counts (sum == n_sims); the API computes
-- P(over line) by summing the bins above the line, exactly like game_sim_projections
-- totals. Bins are 0..N with the last bin a >=N catch-all (12 for hits, 8 for ER).

CREATE TABLE game_sim_pitcher_props (
    game_id        BIGINT  NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    pitcher_id     INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,

    n_sims         INTEGER NOT NULL,   -- histogram denominator for P(over)
    expected_hits  NUMERIC(4,2),       -- hits allowed over the starter's outing
    expected_er    NUMERIC(4,2),       -- earned runs (≈ runs) over the starter's outing
    hits_hist      INTEGER[],          -- counts, bins 0..12 (last is >=12)
    er_hist        INTEGER[],          -- counts, bins 0..8  (last is >=8)

    computed_at    TIMESTAMPTZ DEFAULT NOW(),

    PRIMARY KEY (game_id, pitcher_id)
);
