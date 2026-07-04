"""Hermetic replay of recorded agent runs ("cassettes") — the always-on CI gate.

The live `agent-eval` needs a Gemini key + a running API + seeded data, so it can only gate
conditionally. Cassettes fix that: a cassette is a recorded agent run (the final answer + the
ordered tool steps with their result JSON). Replaying it scores the two DETERMINISTIC layers —
numeric-grounding faithfulness and tool-trajectory recall — with no LLM and no API, so CI gates
every PR hermetically. Record real cassettes post-deploy with `agent-eval --record <dir>`; the
deterministic scorers are identical to the live path, so a green replay means a green live run on
that recorded behaviour.
"""
from __future__ import annotations

import glob
import json
import os

from agent_eval import faithfulness, trajectory


def index_golden(golden_dir: str) -> dict[str, dict]:
    """Map case_id -> golden case (for expected_tools / grounding config)."""
    out: dict[str, dict] = {}
    for path in glob.glob(os.path.join(golden_dir, "*.json")):
        with open(path) as fh:
            case = json.load(fh)
        out[case["id"]] = case
    return out


def _steps_text(steps: list[dict]) -> str:
    return "\n".join(s.get("result_summary", "") for s in steps if s.get("result_summary"))


def score_cassette(case: dict, cassette: dict) -> dict:
    """Score one recorded run against its golden case. Deterministic; no LLM."""
    answer = cassette.get("answer") or ""
    steps = cassette.get("steps") or []
    fg = faithfulness.numeric_grounding(answer, _steps_text(steps))
    called = [s["tool_name"] for s in steps if s.get("tool_name")]
    tj = trajectory.score(case.get("expected_tools", {}), called)
    return {
        "case_id": cassette.get("case_id", case.get("id")),
        "faithfulness": fg,
        "trajectory": tj,
        "passed": fg["passed"] and tj["passed"],
    }


def run_replay(golden_dir: str, cassette_dir: str) -> dict:
    """Score every cassette in cassette_dir against its golden case. Returns aggregates."""
    golden = index_golden(golden_dir)
    results: list[dict] = []
    for path in sorted(glob.glob(os.path.join(cassette_dir, "*.json"))):
        with open(path) as fh:
            cassette = json.load(fh)
        case = golden.get(cassette.get("case_id"))
        if case is None:
            results.append({"case_id": cassette.get("case_id"), "error": "no matching golden case",
                            "passed": False})
            continue
        results.append(score_cassette(case, cassette))

    scored = [r for r in results if "error" not in r]
    faith_rate = (sum(1 for r in scored if r["faithfulness"]["passed"]) / len(scored)) if scored else 1.0
    mean_recall = (sum(r["trajectory"]["recall"] for r in scored) / len(scored)) if scored else 1.0
    return {
        "results": results,
        "cases": len(results),
        "faithfulness_pass_rate": round(faith_rate, 4),
        "trajectory_recall": round(mean_recall, 4),
    }
