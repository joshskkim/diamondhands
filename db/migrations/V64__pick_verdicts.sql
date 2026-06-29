-- The Analyst as the promotion gate on Model's Picks.
-- ============================================================================
-- The bull/skeptic/judge debate now vets each candidate pick: bet/lean stays on
-- Today's Board (with the judge's confidence + a Tail button); pass drops off the
-- board and is shown on Best Lines with the reason. This table is the single
-- verdict source, joined onto /api/odds/best (board + Best Lines both read it)
-- and /api/model-picks. It is also the per-slate CACHE: a selection is debated
-- once per slate (the nightly run does the bulk; the quick loop only debates new
-- candidates), which bounds Gemini cost and keeps the board stable for the day.
--
-- Graceful degradation: when AI is off or a debate fails, record-picks writes NO
-- row here, and a missing verdict means "show normally" (today's mechanistic
-- behaviour). The gate only ever DEMOTES on an explicit verdict='pass'.
--
-- Identity mirrors model_picks_identity (line excluded), so a line move keeps the
-- verdict and the join matches the board's selection key.
CREATE TABLE pick_verdicts (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slate_date       DATE        NOT NULL,
    game_id          BIGINT      NOT NULL REFERENCES games(id),
    market           VARCHAR(20) NOT NULL,
    side             VARCHAR(10) NOT NULL,
    line             NUMERIC(5,2),
    player_id        INTEGER     REFERENCES players(id),
    player_name      VARCHAR(100),
    matchup          VARCHAR(20),
    model_prob       NUMERIC(6,4),
    fair_prob        NUMERIC(6,4),
    edge             NUMERIC(6,4),
    ev_pct           NUMERIC(6,4),
    price_american   INTEGER,
    book             VARCHAR(40),
    verdict          VARCHAR(10) NOT NULL,          -- bet | lean | pass
    confidence       NUMERIC(5,4),                  -- judge's calibrated 0-1
    rationale        TEXT,                          -- one-sentence judge summary
    risks            JSONB       NOT NULL DEFAULT '[]'::jsonb,
    debated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One verdict per selection per slate — the cache key + the join key. player_id is
-- NULL for game markets; NULLS NOT DISTINCT (pg15+) makes those collide as intended.
CREATE UNIQUE INDEX pick_verdicts_identity
    ON pick_verdicts (slate_date, game_id, market, side, player_id) NULLS NOT DISTINCT;

CREATE INDEX idx_pick_verdicts_slate ON pick_verdicts (slate_date);
