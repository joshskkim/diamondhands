"""Diamond Analyst agent evaluation harness.

Three layers (eval-first spine):
  1. faithfulness — every number the agent states must trace to a tool result (no invention),
     plus an LLM-as-judge on a *different* model (faithfulness.py / judge.py).
  2. trajectory   — did the agent call the right tools for the question (trajectory.py).
  3. outcome      — when the agent recommends a bet, grade it against real results + CLV using
     the SAME score-picks machinery (score_recs.py), then aggregate hit-rate/ROI/Brier
     (outcome.py).

The runner (runner.py) drives a live agent over a golden dataset and writes eval_runs/eval_results.
"""
