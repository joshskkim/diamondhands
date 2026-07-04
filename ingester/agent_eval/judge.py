"""LLM-as-judge for faithfulness (Layer 1b). Optional: degrades to a no-op when no judge key.

Critically, the judge runs on a DIFFERENT (stronger) model than the agent under test, to avoid
self-grading bias — the agent answers with gemini-2.5-flash; the judge defaults to gemini-2.5-pro.
It sees the question, the tool outputs the agent actually had, and the answer, and returns strict
JSON {grounded, invented_claims[], faithfulness_score, rationale}.
"""
from __future__ import annotations

import json
import os

_JUDGE_PROMPT = """You grade whether a baseball-betting assistant's ANSWER is faithful to the
TOOL OUTPUTS it was given. An answer is faithful only if every factual claim (players, games,
numbers, prices, edges) is supported by the tool outputs. Penalise any invented or unsupported
claim. Output STRICT JSON only:
{"grounded": <true|false>, "invented_claims": ["..."], "faithfulness_score": <0-1>,
 "rationale": "<one sentence>"}"""


def available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("AGENT_JUDGE_API_KEY"))


def judge(question: str, tool_outputs: str, answer: str,
          model: str | None = None) -> dict | None:
    """Return the judge verdict dict, or None when no judge is configured / on error."""
    key = os.environ.get("AGENT_JUDGE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    model = model or os.environ.get("AGENT_JUDGE_MODEL", "gemini-2.5-pro")
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return None
    try:
        client = genai.Client(api_key=key)
        prompt = (f"QUESTION:\n{question}\n\nTOOL OUTPUTS:\n{tool_outputs[:24000]}\n\n"
                  f"ANSWER:\n{answer}")
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=_JUDGE_PROMPT,
                response_mime_type="application/json",
            ),
        )
        return json.loads(resp.text)
    except Exception as exc:  # noqa: BLE001 — judge is advisory; never fail the run on it
        print(f"[agent-eval] LLM judge unavailable: {exc}")
        return None
