"""Thin client that drives the LIVE Java agent for the eval harness + briefing.

The harness exercises the SAME agent users hit (POST /api/agent), so there is exactly one agent
under test. Auth reuses the normal email+password sign-in (no special bypass) — the harness signs
in as a seeded eval user, sets that user's preferences for the case, then triggers a run and reads
the resulting trajectory back from agent_runs/agent_steps in the DB (the source of truth for the
faithfulness + trajectory layers).
"""
from __future__ import annotations

import json
import os

import requests

DEFAULT_API = os.environ.get("DIAMOND_API_URL", "http://localhost:8080")


class AgentClient:
    def __init__(self, api: str | None = None, email: str | None = None, password: str | None = None):
        self.api = api or DEFAULT_API
        self.email = email or os.environ.get("AGENT_EVAL_EMAIL", "eval@diamondpicks.org")
        self.password = password or os.environ.get("AGENT_EVAL_PASSWORD", "eval-password-123")
        self.session = requests.Session()
        self.user_id: int | None = None

    def sign_in(self) -> int:
        """Sign in (creating the eval user on first run); returns the user id."""
        r = self.session.post(
            f"{self.api}/api/auth/signin",
            json={"email": self.email, "password": self.password}, timeout=30,
        )
        if r.status_code == 401:
            # First run: create the eval account, then it's signed in via the set cookie.
            r = self.session.post(
                f"{self.api}/api/auth/signup",
                json={"email": self.email, "handle": "evalbot", "password": self.password},
                timeout=30,
            )
        r.raise_for_status()
        self.user_id = int(r.json()["id"])
        return self.user_id

    def ask(self, question: str) -> dict:
        """POST a question, consume the SSE stream, return the collected events.

        Returns {answer, statuses[], roles[], confirms[], error}. The trajectory itself is read
        from the DB by run id; this just drives the run and captures what the user would see.
        """
        out: dict = {"answer": None, "statuses": [], "roles": [], "confirms": [], "error": None}
        with self.session.post(
            f"{self.api}/api/agent",
            json={"question": question},
            headers={"Accept": "text/event-stream"},
            stream=True, timeout=180,
        ) as resp:
            resp.raise_for_status()
            event = None
            for raw in resp.iter_lines(decode_unicode=True):
                if raw is None or raw == "":
                    event = None
                    continue
                if raw.startswith("event:"):
                    event = raw[len("event:"):].strip()
                elif raw.startswith("data:"):
                    data = raw[len("data:"):].strip()
                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if event == "answer":
                        out["answer"] = payload.get("text")
                    elif event == "status":
                        out["statuses"].append(payload)
                    elif event == "role":
                        out["roles"].append(payload)
                    elif event == "confirm":
                        out["confirms"].append(payload)
                    elif event == "error":
                        out["error"] = payload.get("message")
        return out

    def confirm(self, token: str) -> str:
        r = self.session.post(f"{self.api}/api/agent/confirm", json={"token": token}, timeout=30)
        r.raise_for_status()
        return r.json().get("result", "")
