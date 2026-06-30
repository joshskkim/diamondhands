-- Benchmark label on eval runs.
-- ============================================================================
-- To A/B agent configurations (e.g. flash vs pro judge), each agent-eval run is
-- tagged with a free-text config label; `compare-evals` then diffs the latest
-- run per label. agent_model/judge_model are already stored (V62) — the label
-- captures axes those columns don't (debate on/off, prompt variant, etc.).
ALTER TABLE eval_runs ADD COLUMN config_label TEXT;
