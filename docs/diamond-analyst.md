# Diamond Analyst — the eval-first agentic layer

Diamond was a passive board: it computes picks, but the user has to come look, every surface is
read-only, and no agent can act. The Diamond Analyst turns it into a **stateful, authenticated
agent** that debates a pick, sizes it to your bankroll, saves it (with your confirmation), and
proactively briefs you — and, critically, is **graded against real outcomes** so we can prove it's
any good.

The design is **eval-first** because that's the rare signal: every pick in this domain has ground
truth (it gets graded; CLV/Brier already tracked), which lets us build the agent *and* an
outcome-grounded eval harness most projects can't.

## The four anchors, one agent

- **B — conversational co-pilot** (`api/.../ai/AgentService.java`): the stateless "Ask Diamond"
  loop, upgraded with per-user memory (`user_preferences`), deterministic Kelly sizing
  (`KellyCalculator`), and HITL write actions. `POST /api/agent` (SSE, authenticated).
- **F — Bull/Skeptic/Judge debate** (`DebateOrchestrator`): the reasoning engine. The bull argues
  with the general read tools; the skeptic challenges with the *same* contrarian signals the
  Model's Picks bar vetoes on (`SkepticToolRegistry` → sim disagreement, hit-rate traffic light,
  line movement/CLV, sample size); a stronger judge model emits a calibrated confidence + verdict.
- **E — eval harness** (`ingester/agent_eval/`): three layers — (1) faithfulness (numeric grounding
  + LLM-as-judge on a *different* model), (2) tool-trajectory recall, (3) outcome-grounded grading
  that reuses `picks.py`'s `_grade`/`_closing_quote` verbatim, then aggregates hit-rate / CLV / ROI
  and a **Brier on the judge's confidence vs realized `won`**.
- **A — proactive briefing** (`ingester/.../commands/briefing.py`): a Discord recap folded into the
  9am `daily` chain after the prior slate is graded.

## HITL writes (the model never mutates)

A write tool only **proposes** a validated action (with a deterministic Kelly stake). The server
streams a `confirm` event carrying an **HMAC-signed token** (`ActionTokenService`); `POST
/api/agent/confirm` replays the exact payload — no second model call, so a confirmed write can't
drift from what the user approved. Guardrails: refuse-to-invent prompt + post-hoc numeric grounding,
bounded tool iterations, Kelly fraction capped at 0.5, no sizing without a bankroll, full audit in
`agent_runs`/`agent_steps`.

## Schema (`db/migrations/V62__agent.sql`)

`user_preferences` (memory) · `agent_threads`/`agent_runs`/`agent_steps` (trajectory) ·
`agent_recommendations` + `user_bets` (carry model_picks' selection-identity + CLV grade columns, so
the score-picks grader joins unchanged) · `line_alerts` · `eval_runs`/`eval_results`.

## Verify it end-to-end

1. **Live agent** (needs `AI_ENABLED=true GEMINI_API_KEY=…`): start the API, sign in, then
   `POST /api/agent {"question":"best pick tonight, sized for my 100u bankroll"}` →
   watch the bull/skeptic/judge `role` turns + a `confirm` event → `POST /api/agent/confirm` →
   one `agent_recommendations` row + an `agent_steps` trajectory.
2. **Eval harness:**
   `cd ingester && uv run python main.py agent-eval --golden agent_eval/golden`
   → per-layer table, writes `eval_runs`/`eval_results`, exits non-zero if the faithfulness or
   tool-recall gate fails. CI: `.github/workflows/agent-eval.yml` (deterministic layer-logic tests
   always; full live run when a `GEMINI_API_KEY` secret is set).
3. **Outcome grading (deterministic, no waiting):** pick a past settled slate, insert an
   `agent_recommendation` for a settled selection, run
   `uv run python main.py score-agent-recs --date <past>` → `won`/`result_value`/`clv` populate and
   **match the equivalent `model_picks` grade** (same code → identical numbers — the regression
   check that the reuse is correct). Then `agent-eval --layer outcome` → hit-rate / CLV / ROI +
   the judge-confidence Brier.

## Fast-follows

Email/web-push channels + per-user briefing fan-out · line-alert firing loop · full conversational
memory replay · expose write tools via the MCP server · hermetic CI via recorded tool-output
cassettes · Grafana panels over `eval_results` · adversarial "make the model invent a number"
golden cases.
