"""Layer 2 — tool-trajectory correctness. Pure, deterministic, no LLM.

Reads the actual tool-call sequence the agent took (from agent_steps) and compares it to the
golden case's expected tools. The gate metric is required-tool recall: every tool the question
*needs* must have been called. Tool-set precision (did it call irrelevant tools) is reported but
not gated. The debate roles (bull/skeptic/judge) count as tool usage too — their tool calls are
in agent_steps with role bull/skeptic.
"""
from __future__ import annotations


def load_called_tools(conn, run_id: int) -> list[str]:
    """The ordered tool names the agent actually called (model + debate roles), tools only."""
    rows = conn.execute(
        "SELECT tool_name FROM agent_steps WHERE run_id = %s AND tool_name IS NOT NULL "
        "ORDER BY step_no",
        (run_id,),
    ).fetchall()
    return [r[0] for r in rows]


def score(expected: dict, called: list[str]) -> dict:
    """Compare called tools to expected. expected = {required:[...], optional:[...]}.

    Returns {passed, recall, precision, missing, called}.
    recall = required hit / required total (the gate); precision = (required ∪ optional hits)
    over distinct called.
    """
    required = set(expected.get("required", []))
    optional = set(expected.get("optional", []))
    called_set = set(called)

    missing = sorted(required - called_set)
    recall = 1.0 if not required else (len(required & called_set) / len(required))
    allowed = required | optional
    precision = 1.0 if not called_set else (len(called_set & allowed) / len(called_set))

    return {
        "passed": not missing,
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "missing": missing,
        "called": called,
    }
