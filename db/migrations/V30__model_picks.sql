-- Daily Model's Picks, persisted server-side (the home board computes them
-- client-side and previously kept NO record — a 0/3 day couldn't even be audited).
-- record-picks captures the day's board (same bar as web/components/home/
-- model-picks.tsx); score-picks fills result/won the next morning once scores
-- (and, for props, player_game_stats) exist. won stays NULL on push/void.
CREATE TABLE IF NOT EXISTS model_picks (
    slate_date     date         NOT NULL,
    rank           integer      NOT NULL,            -- 1..N board order
    game_id        bigint       NOT NULL REFERENCES games(id),
    market         varchar(20)  NOT NULL,            -- total | moneyline | run_line | hit | hr
    side           varchar(10)  NOT NULL,
    line           numeric(5,2),
    player_id      integer      REFERENCES players(id),
    player_name    varchar(100),
    matchup        varchar(20),
    model_prob     numeric(6,4) NOT NULL,
    fair_prob      numeric(6,4) NOT NULL,
    edge           numeric(6,4) NOT NULL,
    ev_pct         numeric(6,4) NOT NULL,
    price_american integer      NOT NULL,
    book           varchar(40),
    strong         boolean      NOT NULL DEFAULT false,
    model_version  varchar(20)  NOT NULL,
    recorded_at    timestamptz  NOT NULL DEFAULT now(),
    result_value   numeric(6,2),                     -- actual total / hits / HR / margin
    won            boolean,                          -- NULL = unscored or push/void
    scored_at      timestamptz,
    PRIMARY KEY (slate_date, rank)
);

CREATE INDEX IF NOT EXISTS idx_model_picks_unscored
    ON model_picks (slate_date) WHERE scored_at IS NULL;
