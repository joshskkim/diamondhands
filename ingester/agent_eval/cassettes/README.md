# Cassettes — recorded agent runs for hermetic CI

Each file is a recorded agent run (the final answer + the ordered tool steps with their result
JSON) keyed to a golden case by `case_id`. `agent-eval --replay agent_eval/cassettes` scores the
deterministic layers (numeric-grounding faithfulness + tool-trajectory recall) against them with no
LLM, API, or DB — so CI gates every PR hermetically.

**Regenerate from real runs after deploy** (needs a key + running API):
```
uv run python main.py agent-eval --golden agent_eval/golden --record agent_eval/cassettes
```
The deterministic scorers are identical to the live path, so a green replay reflects the real
recorded behaviour. The committed seeds below are realistic hand-authored stand-ins until the first
recorded set replaces them.
