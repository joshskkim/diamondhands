"""daily-briefing: push a proactive recap to the user out-of-app (anchor A).

Turns the passive board into something that reaches you. Folded into the 9am `daily` chain after
the prior slate is graded, it: (a) summarises yesterday's graded Model's Picks + the Diamond
Analyst's own recommendation record, (b) optionally has the SAME agent write a natural-language
recap (one voice, and it's the agent under eval), and (c) POSTs it to a Discord webhook — the
lowest-friction channel (one env var, no DKIM/VAPID). Email/web-push + per-user fan-out are
fast-follows.
"""
from __future__ import annotations

import argparse
import os
from datetime import timedelta

import requests

from ingester.db import eastern_today, get_connection

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
DEFAULT_API = os.environ.get("DIAMOND_API_URL", "http://localhost:8080")


def _record(conn, table: str, slate) -> tuple[int, int, int, float | None]:
    """(wins, losses, pushes, avg_clv) for a graded selection table on `slate`."""
    row = conn.execute(
        f"""
        SELECT COUNT(*) FILTER (WHERE won IS TRUE),
               COUNT(*) FILTER (WHERE won IS FALSE),
               COUNT(*) FILTER (WHERE won IS NULL AND scored_at IS NOT NULL),
               AVG(clv)
        FROM {table}
        WHERE slate_date = %s AND scored_at IS NOT NULL
        """,
        (slate,),
    ).fetchone()
    avg_clv = float(row[3]) if row[3] is not None else None
    return int(row[0] or 0), int(row[1] or 0), int(row[2] or 0), avg_clv


def _templated(yest, picks_rec, agent_rec) -> str:
    w, losses, p, clv = picks_rec
    aw, al, _ap, aclv = agent_rec
    clv_str = f", avg CLV {clv:+.3f}" if clv is not None else ""
    aclv_str = f", avg CLV {aclv:+.3f}" if aclv is not None else ""
    lines = [
        f"**Diamond briefing — {eastern_today()}**",
        f"Yesterday ({yest}): Model's Picks {w}-{losses}" + (f" ({p} push)" if p else "") + clv_str + ".",
    ]
    if aw + al > 0:
        lines.append(f"Diamond Analyst recommendations: {aw}-{al}{aclv_str}.")
    lines.append("See tonight's board: https://diamondpicks.org")
    return "\n".join(lines)


def _agent_recap(yest) -> str | None:
    """Have the live agent write the recap (best effort; None if the agent isn't reachable)."""
    try:
        from agent_eval.agent_client import AgentClient
        client = AgentClient(api=DEFAULT_API)
        client.sign_in()
        q = (f"Write a short, friendly Discord briefing (<120 words). Summarise the model's results "
             f"for {yest} and call out tonight's single best pick with its edge. No betting advice "
             f"disclaimer needed.")
        return (client.ask(q) or {}).get("answer")
    except Exception as exc:  # noqa: BLE001 — recap is enrichment; fall back to the template
        print(f"[daily-briefing] agent recap unavailable ({exc}); using templated summary")
        return None


def cmd_daily_briefing(args: argparse.Namespace) -> None:
    webhook = getattr(args, "webhook", None) or DISCORD_WEBHOOK_URL
    yest = eastern_today() - timedelta(days=1)

    conn = get_connection()
    try:
        picks_rec = _record(conn, "model_picks", yest)
        agent_rec = _record(conn, "agent_recommendations", yest)
    finally:
        conn.close()

    body = _templated(yest, picks_rec, agent_rec)
    if not getattr(args, "no_agent", False):
        recap = _agent_recap(yest)
        if recap:
            body = recap + "\n\n" + body

    if not webhook:
        print("[daily-briefing] DISCORD_WEBHOOK_URL not set; printing instead:\n" + body)
        return
    resp = requests.post(webhook, json={"content": body[:1900]}, timeout=30)
    resp.raise_for_status()
    print(f"[daily-briefing] posted briefing for {yest} ({len(body)} chars).")
