"""agent-eval: run the live Diamond Analyst over a golden dataset and score it.

Layers 1 (faithfulness) + 2 (trajectory) run here against a live agent and gate CI. Layer 3
(outcome) aggregates whatever recommendations have since been graded and is reported/tracked but
not CI-gated (it needs real game results, so it runs nightly in cron). Writes eval_runs +
eval_results and exits non-zero when a gate fails.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys

from ingester.db import get_connection
from agent_eval import faithfulness, judge, outcome, trajectory
from agent_eval.agent_client import AgentClient

REQUIRED_RECALL_GATE = 0.9
FAITHFULNESS_GATE = 0.9


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                       text=True).strip()
    except Exception:  # noqa: BLE001
        return None


def _load_cases(golden_dir: str) -> list[dict]:
    cases = []
    for path in sorted(glob.glob(os.path.join(golden_dir, "*.json"))):
        with open(path) as fh:
            cases.append(json.load(fh))
    return cases


def _set_prefs(conn, user_id: int, ctx: dict) -> None:
    """Apply a case's user_context to the eval user so sizing behaves deterministically."""
    conn.execute(
        """
        INSERT INTO user_preferences (user_id, bankroll_units, kelly_fraction, updated_at)
        VALUES (%s, %s, %s, now())
        ON CONFLICT (user_id) DO UPDATE SET
            bankroll_units = EXCLUDED.bankroll_units,
            kelly_fraction = EXCLUDED.kelly_fraction,
            updated_at = now()
        """,
        (user_id, ctx.get("bankroll_units"), ctx.get("kelly_fraction", 0.25)),
    )
    conn.commit()


def _latest_run_id(conn, user_id: int) -> int | None:
    row = conn.execute(
        "SELECT id FROM agent_runs WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,)
    ).fetchone()
    return row[0] if row else None


def _steps_text(conn, run_id: int) -> str:
    rows = conn.execute(
        "SELECT result_summary FROM agent_steps WHERE run_id = %s AND result_summary IS NOT NULL "
        "ORDER BY step_no",
        (run_id,),
    ).fetchall()
    return "\n".join(r[0] for r in rows)


def cmd_agent_eval(args: argparse.Namespace) -> None:
    layer = getattr(args, "layer", "all")
    conn = get_connection()
    try:
        # Open the eval_run header up front so eval_results can FK to it.
        run_id = conn.execute(
            "INSERT INTO eval_runs (git_sha, dataset_version, agent_model, judge_model) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (_git_sha(), os.path.basename(getattr(args, "golden", "golden")),
             os.environ.get("AI_MODEL", "gemini-2.5-flash"),
             os.environ.get("AGENT_JUDGE_MODEL", "gemini-2.5-pro")),
        ).fetchone()[0]
        conn.commit()

        recalls: list[float] = []
        faith_pass: list[bool] = []
        n_cases = 0

        if layer in ("all", "faithfulness", "trajectory"):
            client = AgentClient(api=getattr(args, "api", None))
            user_id = client.sign_in()
            for case in _load_cases(getattr(args, "golden", "agent_eval/golden")):
                n_cases += 1
                _set_prefs(conn, user_id, case.get("user_context", {}))
                result = client.ask(case["question"])
                # Auto-confirm save_recommendation proposals so the rec lands for the outcome layer.
                for c in result.get("confirms", []):
                    if c.get("action") == "save_recommendation":
                        try:
                            client.confirm(c["token"])
                        except Exception as exc:  # noqa: BLE001
                            print(f"[agent-eval] confirm failed: {exc}")

                rid = _latest_run_id(conn, user_id)
                steps_text = _steps_text(conn, rid) if rid else ""
                called = trajectory.load_called_tools(conn, rid) if rid else []
                answer = result.get("answer") or ""

                # Layer 1: numeric grounding (gate) + optional LLM judge (advisory).
                fg = faithfulness.numeric_grounding(answer, steps_text)
                jv = None
                if judge.available():
                    jv = judge.judge(case["question"], steps_text, answer)
                faith_passed = fg["passed"] and (jv is None or jv.get("grounded", True))
                faith_pass.append(faith_passed)
                _write_result(conn, run_id, case["id"], "faithfulness", faith_passed,
                              fg["score"], jv.get("rationale") if jv else None,
                              {"orphans": fg["orphans"], "judge": jv})

                # Layer 2: tool trajectory (recall gate).
                tj = trajectory.score(case.get("expected_tools", {}), called)
                recalls.append(tj["recall"])
                _write_result(conn, run_id, case["id"], "trajectory", tj["passed"],
                              tj["recall"], None, tj)

                flag = "✓" if (faith_passed and tj["passed"]) else "✗"
                print(f"  {flag} {case['id']}: faith={fg['score']:.2f}"
                      f"{' orphans=' + ','.join(fg['orphans']) if fg['orphans'] else ''} "
                      f"recall={tj['recall']:.2f}"
                      f"{' missing=' + ','.join(tj['missing']) if tj['missing'] else ''}")

        # Layer 3: outcome aggregation (always computed; reported, not gated here).
        agg = outcome.aggregate(conn, since_days=getattr(args, "since_days", None))
        _write_result(conn, run_id, "_aggregate", "outcome", None, agg.get("brier"), None, agg)

        mean_recall = sum(recalls) / len(recalls) if recalls else 1.0
        faith_rate = sum(faith_pass) / len(faith_pass) if faith_pass else 1.0
        conn.execute(
            "UPDATE eval_runs SET cases=%s, faithfulness_pass_rate=%s, trajectory_recall=%s, "
            "outcome_hit_rate=%s, outcome_avg_clv=%s, outcome_roi=%s, outcome_brier=%s, "
            "finished_at=now() WHERE id=%s",
            (n_cases, round(faith_rate, 4), round(mean_recall, 4),
             agg.get("hit_rate"), agg.get("avg_clv"), agg.get("roi"), agg.get("brier"), run_id),
        )
        conn.commit()
    finally:
        conn.close()

    print(f"\n[agent-eval] run #{run_id}: {n_cases} cases | "
          f"faithfulness pass-rate {faith_rate:.2f} (gate {FAITHFULNESS_GATE}) | "
          f"required-tool recall {mean_recall:.2f} (gate {REQUIRED_RECALL_GATE})")
    print(f"[agent-eval] outcome (graded recs): hit_rate={agg.get('hit_rate')} "
          f"avg_clv={agg.get('avg_clv')} roi={agg.get('roi')} brier={agg.get('brier')} "
          f"(n={agg.get('graded')})")

    failed = (faith_rate < FAITHFULNESS_GATE) or (mean_recall < REQUIRED_RECALL_GATE)
    if failed:
        print("[agent-eval] GATE FAILED", file=sys.stderr)
        sys.exit(1)
    print("[agent-eval] gates passed.")


def _write_result(conn, run_id, case_id, layer, passed, score, rationale, details) -> None:
    conn.execute(
        "INSERT INTO eval_results (eval_run_id, case_id, layer, passed, score, judge_rationale, "
        "details_json) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)",
        (run_id, case_id, layer, passed, score, rationale, json.dumps(details, default=str)),
    )
