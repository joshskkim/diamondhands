-- Backtest projection outputs (written by: project --as-of YYYY-MM-DD).
-- backtest_run_id will FK to backtest_runs in a future migration.

CREATE TABLE backtest_projections (
    backtest_run_id      BIGINT NOT NULL,
    game_id              BIGINT NOT NULL,
    player_id            INT    NOT NULL,
    as_of_date           DATE   NOT NULL,
    expected_pa          NUMERIC(4,2),
    p_hit_1plus          NUMERIC(5,4),
    p_hit_2plus          NUMERIC(5,4),
    p_hr                 NUMERIC(5,4),
    p_k_1plus            NUMERIC(5,4),
    expected_hits        NUMERIC(4,3),
    expected_total_bases NUMERIC(4,3),
    PRIMARY KEY (backtest_run_id, game_id, player_id)
);

CREATE INDEX idx_btp_run  ON backtest_projections(backtest_run_id);
CREATE INDEX idx_btp_game ON backtest_projections(game_id);
