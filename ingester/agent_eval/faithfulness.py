"""Layer 1 — faithfulness / grounding.

Two checks, deterministic first:
  (a) numeric grounding — every *stat-like* number the agent states (a probability, percentage,
      edge, EV, or American price) must trace to a number that actually appeared in a tool result
      for that run (captured in agent_steps). An orphan number is invention → fail. We ignore
      trivial small integers (ranks, innings, counts, dates) to keep false positives near zero —
      the risk in a betting answer is a fabricated edge/price, not the number "3".
  (b) LLM-as-judge (judge.py, optional) on a *different/stronger* model — catches unsupported
      qualitative claims the regex can't.

The gate is (a): zero orphan numbers. (b) is advisory unless a judge model is configured.
"""
from __future__ import annotations

import re

# A stat-like number: a decimal (0.62), a percent (62%), or an American price (+130 / -110).
_PERCENT = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d+)?)\s?%")
_PRICE = re.compile(r"(?<![\w.])([+-]\d{3,4})(?![\d.])")
_DECIMAL = re.compile(r"(?<![\w])(\d?\.\d+)(?![\d%])")
_ANY_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")

_TOL = 0.011  # absolute tolerance (covers rounding: 0.62 vs 0.618, 62% vs 61.8%)


def _pool(steps_text: str) -> list[float]:
    """All numbers present in the run's tool-result JSON (the grounding pool)."""
    return [float(m) for m in _ANY_NUMBER.findall(steps_text or "")]


def _matches(value: float, pool: list[float]) -> bool:
    return any(abs(value - p) <= _TOL for p in pool)


def extract_claimed_numbers(answer: str) -> list[tuple[str, float]]:
    """Stat-like numbers the answer asserts, as (raw, normalized_value)."""
    claims: list[tuple[str, float]] = []
    for raw in _PERCENT.findall(answer):
        claims.append((raw + "%", float(raw) / 100.0))  # 62% -> 0.62 (prob basis)
    for raw in _PRICE.findall(answer):
        claims.append((raw, float(raw)))
    for raw in _DECIMAL.findall(answer):
        claims.append((raw, float(raw)))
    return claims


def numeric_grounding(answer: str, steps_text: str) -> dict:
    """Returns {passed, orphans[], checked, score}. score = grounded / checked (1.0 if none)."""
    pool = _pool(steps_text)
    claims = extract_claimed_numbers(answer or "")
    orphans: list[str] = []
    for raw, value in claims:
        # A percent can also be grounded against its raw form (62% vs a "62" in the JSON), or
        # against the probability basis (0.62). A price grounds on its own value.
        candidates = {value}
        if raw.endswith("%"):
            candidates.add(value * 100.0)
        if not any(_matches(c, pool) for c in candidates):
            orphans.append(raw)
    checked = len(claims)
    grounded = checked - len(orphans)
    return {
        "passed": not orphans,
        "orphans": orphans,
        "checked": checked,
        "score": round(grounded / checked, 4) if checked else 1.0,
    }
