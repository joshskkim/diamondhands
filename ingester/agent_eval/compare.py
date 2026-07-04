"""compare-evals: A/B agent configurations on the golden set.

Benchmarking a non-deterministic agent is itself a resume-worthy artifact: run the golden suite
under each config (e.g. `agent-eval --label flash-judge` then `--label pro-judge`, varying
AGENT_JUDGE_MODEL between runs), and this tabulates the latest run per label so you can see the
faithfulness / trajectory / outcome trade-off. The aggregation is pure + unit-tested; the command
just feeds it rows from eval_runs.
"""
from __future__ import annotations

import argparse

from ingester.db import get_connection

_METRICS = ("faithfulness_pass_rate", "trajectory_recall", "outcome_hit_rate",
            "outcome_avg_clv", "outcome_roi", "outcome_brier")


def latest_per_config(rows: list[dict]) -> list[dict]:
    """Given eval_runs rows (each a dict with id, a config key, and the metrics), return the most
    recent run per config (highest id wins), sorted by config label. Pure for unit-testing."""
    best: dict[str, dict] = {}
    for r in rows:
        key = r.get("config_label") or f"{r.get('agent_model')}/{r.get('judge_model')}"
        if key not in best or r["id"] > best[key]["id"]:
            best[key] = {**r, "config": key}
    return [best[k] for k in sorted(best)]


def _fmt(v) -> str:
    return "—" if v is None else f"{float(v):.3f}"


def cmd_compare_evals(args: argparse.Namespace) -> None:
    limit = getattr(args, "limit", 50)
    conn = get_connection()
    try:
        cols = "id, config_label, agent_model, judge_model, cases, " + ", ".join(_METRICS)
        raw = conn.execute(
            f"SELECT {cols} FROM eval_runs WHERE finished_at IS NOT NULL "
            f"ORDER BY id DESC LIMIT %s",
            (limit,),
        ).fetchall()
    finally:
        conn.close()

    keys = ["id", "config_label", "agent_model", "judge_model", "cases", *_METRICS]
    rows = [dict(zip(keys, r)) for r in raw]
    summary = latest_per_config(rows)
    if not summary:
        print("[compare-evals] no finished eval runs yet — run `agent-eval --label <name>` first.")
        return

    header = f"{'config':<22} {'cases':>5} {'faith':>7} {'recall':>7} {'hit':>7} {'clv':>7} {'roi':>7} {'brier':>7}"
    print(header)
    print("-" * len(header))
    for s in summary:
        print(f"{s['config'][:22]:<22} {str(s.get('cases') or 0):>5} "
              f"{_fmt(s.get('faithfulness_pass_rate')):>7} {_fmt(s.get('trajectory_recall')):>7} "
              f"{_fmt(s.get('outcome_hit_rate')):>7} {_fmt(s.get('outcome_avg_clv')):>7} "
              f"{_fmt(s.get('outcome_roi')):>7} {_fmt(s.get('outcome_brier')):>7}")
    print("\n(faith/recall/hit higher better; brier lower better; outcome cols need graded recs.)")
