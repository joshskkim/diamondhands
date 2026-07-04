-- Diamond Analyst — the agentic layer (eval-first).
-- ============================================================================
-- The app was a passive board: it computes picks but nothing reaches the user
-- and no agent can act. This adds a stateful per-user agent (the "Diamond
-- Analyst") plus the eval spine that grades it. The design choice that makes the
-- eval cheap: every selection here carries the SAME identity + grade columns as
-- model_picks (see V30/V57/V58), so the score-picks grader/CLV code grades an
-- agent recommendation with zero query changes.
--
--   selection identity = (game_id, market, side, line, player_id)
--   grade cols         = result_value, won, scored_at, close_*, clv*  (cf. V57)
--
-- Everything user-owned references users.id (V25), keeping identity swappable.

-- ── Long-term memory: per-user preferences / bankroll ───────────────────────
-- One row per user; the agent loads this to personalise (Kelly sizing, briefing
-- target). kelly_fraction is capped in app code (<= 0.5) but defaulted to a
-- conservative quarter-Kelly here.
CREATE TABLE user_preferences (
    user_id            BIGINT      PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    bankroll_units     NUMERIC(10,2),                 -- NULL => sizing disabled until set
    unit_size_usd      NUMERIC(10,2),
    kelly_fraction     NUMERIC(4,3) NOT NULL DEFAULT 0.250,
    risk_profile       TEXT        NOT NULL DEFAULT 'balanced',  -- conservative|balanced|aggressive
    favorite_teams     JSONB       NOT NULL DEFAULT '[]'::jsonb,
    briefing_channel   TEXT,                          -- discord (only channel in slice) | NULL=off
    discord_webhook_url TEXT,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Conversation session ────────────────────────────────────────────────────
CREATE TABLE agent_threads (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id        BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_agent_threads_user ON agent_threads (user_id, last_active_at DESC);

-- ── Run header: one per ask (trajectory root + observability) ───────────────
-- channel distinguishes interactive (web) from the offline callers (briefing,
-- eval) so the eval harness and the daily briefing share the SAME agent yet are
-- separable in the logs.
CREATE TABLE agent_runs (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    thread_id         BIGINT REFERENCES agent_threads(id) ON DELETE SET NULL,
    user_id           BIGINT REFERENCES users(id) ON DELETE SET NULL,
    channel           TEXT NOT NULL DEFAULT 'web',    -- web | briefing | eval
    question          TEXT NOT NULL,
    final_answer      TEXT,
    status            TEXT NOT NULL DEFAULT 'running', -- running | done | error
    model             TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    tool_calls        INTEGER NOT NULL DEFAULT 0,
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at       TIMESTAMPTZ
);
CREATE INDEX idx_agent_runs_user ON agent_runs (user_id, started_at DESC);
CREATE INDEX idx_agent_runs_channel ON agent_runs (channel, started_at DESC);

-- ── Per-decision trajectory (the eval Layer 2 source of truth) ──────────────
-- role lets the debate roles (bull/skeptic/judge) and plain tool/model turns
-- live in one ordered log. args_json/result_summary back the Layer-1 numeric
-- grounding check (every number in the answer must appear in a tool result).
CREATE TABLE agent_steps (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id         BIGINT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    step_no        INTEGER NOT NULL,
    role           TEXT NOT NULL,                     -- model|tool|bull|skeptic|judge
    tool_name      TEXT,
    args_json      JSONB,
    result_summary TEXT,
    latency_ms     INTEGER,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_agent_steps_run ON agent_steps (run_id, step_no);

-- ── Agent recommendations: the outcome-grounded join target ─────────────────
-- A judged pick the agent stands behind. confidence is the judge's calibrated
-- 0-1 belief — graded against realized `won` for a Brier score (does the agent
-- know when it's right?). Grade cols mirror model_picks so score-agent-recs is a
-- near-clone of score-picks.
CREATE TABLE agent_recommendations (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id           BIGINT REFERENCES agent_runs(id) ON DELETE SET NULL,
    user_id          BIGINT REFERENCES users(id) ON DELETE SET NULL,
    slate_date       DATE        NOT NULL,
    game_id          BIGINT      NOT NULL REFERENCES games(id),
    market           VARCHAR(20) NOT NULL,
    side             VARCHAR(10) NOT NULL,
    line             NUMERIC(5,2),
    player_id        INTEGER     REFERENCES players(id),
    player_name      VARCHAR(100),
    model_prob       NUMERIC(6,4),
    fair_prob        NUMERIC(6,4),
    edge             NUMERIC(6,4),
    ev_pct           NUMERIC(6,4),
    price_american   INTEGER,
    book             VARCHAR(40),
    stake_units      NUMERIC(10,2),
    confidence       NUMERIC(5,4),                    -- judge's calibrated 0-1
    recorded_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- grade cols (cf. V30 + V57) — filled by score-agent-recs
    result_value     NUMERIC(6,2),
    won              BOOLEAN,
    scored_at        TIMESTAMPTZ,
    close_price_american INTEGER,
    close_price_decimal  NUMERIC(7,3),
    close_fair_prob      NUMERIC(6,4),
    clv                  NUMERIC(6,4),
    clv_captured_at      TIMESTAMPTZ
);
CREATE INDEX idx_agent_recs_unscored ON agent_recommendations (slate_date) WHERE scored_at IS NULL;
CREATE INDEX idx_agent_recs_user ON agent_recommendations (user_id, slate_date DESC);

-- ── Personal bet tracker: graded by the same machinery => personal ROI/CLV ──
CREATE TABLE user_bets (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id          BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    slate_date       DATE        NOT NULL,
    game_id          BIGINT      NOT NULL REFERENCES games(id),
    market           VARCHAR(20) NOT NULL,
    side             VARCHAR(10) NOT NULL,
    line             NUMERIC(5,2),
    player_id        INTEGER     REFERENCES players(id),
    player_name      VARCHAR(100),
    stake_units      NUMERIC(10,2),
    price_american   INTEGER,
    book             VARCHAR(40),
    status           TEXT NOT NULL DEFAULT 'open',    -- open | settled | void
    placed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- grade cols (cf. V30 + V57)
    result_value     NUMERIC(6,2),
    won              BOOLEAN,
    scored_at        TIMESTAMPTZ,
    close_price_american INTEGER,
    close_price_decimal  NUMERIC(7,3),
    close_fair_prob      NUMERIC(6,4),
    clv                  NUMERIC(6,4),
    clv_captured_at      TIMESTAMPTZ
);
CREATE INDEX idx_user_bets_unscored ON user_bets (slate_date) WHERE scored_at IS NULL;
CREATE INDEX idx_user_bets_user ON user_bets (user_id, slate_date DESC);
-- One open bet per selection per user per slate (idempotent log).
CREATE UNIQUE INDEX user_bets_identity
    ON user_bets (user_id, slate_date, game_id, market, side, player_id) NULLS NOT DISTINCT;

-- ── Line alerts (firing deferred to a fast-follow; schema lands now) ─────────
CREATE TABLE line_alerts (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id              BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    slate_date           DATE   NOT NULL,
    game_id              BIGINT REFERENCES games(id),
    market               VARCHAR(20) NOT NULL,
    side                 VARCHAR(10) NOT NULL,
    line                 NUMERIC(5,2),
    player_id            INTEGER REFERENCES players(id),
    target_price_american INTEGER,
    target_edge          NUMERIC(6,4),
    status               TEXT NOT NULL DEFAULT 'armed', -- armed | fired | cancelled
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    fired_at             TIMESTAMPTZ
);
CREATE INDEX idx_line_alerts_armed ON line_alerts (slate_date) WHERE status = 'armed';

-- ── Eval results: backs the CI gate + a regression view over time ───────────
CREATE TABLE eval_runs (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    git_sha              TEXT,
    dataset_version      TEXT,
    agent_model          TEXT,
    judge_model          TEXT,
    cases                INTEGER NOT NULL DEFAULT 0,
    faithfulness_pass_rate NUMERIC(5,4),
    trajectory_recall    NUMERIC(5,4),
    outcome_hit_rate     NUMERIC(5,4),
    outcome_avg_clv      NUMERIC(6,4),
    outcome_roi          NUMERIC(7,4),
    outcome_brier        NUMERIC(6,4),
    started_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at          TIMESTAMPTZ
);

CREATE TABLE eval_results (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    eval_run_id     BIGINT NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    case_id         TEXT NOT NULL,
    layer           TEXT NOT NULL,                    -- faithfulness | trajectory | outcome
    passed          BOOLEAN,
    score           NUMERIC(6,4),
    judge_rationale TEXT,
    details_json    JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_eval_results_run ON eval_results (eval_run_id, layer);
