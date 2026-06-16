"""Total-games model: de-biased mean + empirical residual distribution.

The closed-form i.i.d. simulator is biased (over-counts ~+2) AND underdispersed
(real matches have fatter game-count tails than independent points imply). We fix
both empirically, mirroring MLB workload.py's walk-forward residual histogram:

  predicted mean  = a + b * exp_total_games          (affine de-bias)
  predictive dist = mean + residual,  residual ~ empirical residuals (per best_of)

so P(total > line) and the PIT come straight from the data's own spread. Residuals
are fit on a train window and applied out-of-sample, so a flat OOS PIT is a genuine
calibration result.
"""
from __future__ import annotations

import bisect
import json
from collections import defaultdict
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "models" / "tennis_games_calibration.json"
_NQ = 201  # stored residual quantiles per best_of


class GamesCalibrator:
    def __init__(self, a: float, b: float, residuals: dict[int, list[float]] | None = None):
        self.a = a
        self.b = b
        # sorted residual quantiles keyed by best_of (empty -> mean-only, no dist)
        self.residuals = residuals or {}

    @classmethod
    def load(cls, path: str | Path | None = None) -> "GamesCalibrator | None":
        p = Path(path) if path is not None else DEFAULT_PATH
        if not p.exists():
            return None
        d = json.loads(p.read_text())
        resid = {int(k): v for k, v in d.get("residuals", {}).items()}
        return cls(float(d["a"]), float(d["b"]), resid)

    def mean(self, exp_games: float) -> float:
        return self.a + self.b * exp_games

    def _resid(self, best_of: int) -> list[float] | None:
        return self.residuals.get(best_of) or self.residuals.get(3) or (
            next(iter(self.residuals.values()), None))

    def p_over_at_mean(self, mean: float, best_of: int, line: float) -> float | None:
        """P(total > line) given an already-calibrated mean. None if no residuals."""
        q = self._resid(best_of)
        if not q:
            return None
        idx = bisect.bisect_right(q, line - mean)
        return 1.0 - idx / len(q)

    def pit_at_mean(self, mean: float, best_of: int, actual: int) -> float | None:
        q = self._resid(best_of)
        if not q:
            return None
        return bisect.bisect_right(q, actual - mean) / len(q)

    def p_over(self, exp_games: float, best_of: int, line: float) -> float | None:
        """P(total > line) from a RAW closed-form expected-games (applies the mean de-bias)."""
        return self.p_over_at_mean(self.mean(exp_games), best_of, line)

    def pit(self, exp_games: float, best_of: int, actual: int) -> float | None:
        return self.pit_at_mean(self.mean(exp_games), best_of, actual)


def fit_linear(predicted: list[float], actual: list[float]) -> tuple[float, float]:
    """Least-squares a, b for actual ≈ a + b*predicted."""
    n = len(predicted)
    mx = sum(predicted) / n
    my = sum(actual) / n
    sxx = sum((x - mx) ** 2 for x in predicted)
    sxy = sum((x - mx) * (y - my) for x, y in zip(predicted, actual))
    b = sxy / sxx if sxx else 1.0
    return (my - b * mx, b)


def _quantiles(sorted_vals: list[float], k: int = _NQ) -> list[float]:
    n = len(sorted_vals)
    return [sorted_vals[min(n - 1, round(i / (k - 1) * (n - 1)))] for i in range(k)]


def fit_games_model(records: list[tuple[float, int, int]]) -> tuple[float, float, dict[str, list[float]]]:
    """records: (exp_games, actual, best_of) -> (a, b, residual_quantiles_by_best_of)."""
    preds = [r[0] for r in records]
    actual = [float(r[1]) for r in records]
    a, b = fit_linear(preds, actual)
    by_bo: dict[int, list[float]] = defaultdict(list)
    for pred, act, bo in records:
        by_bo[bo].append(act - (a + b * pred))
    residuals = {str(bo): _quantiles(sorted(res)) for bo, res in by_bo.items() if len(res) >= 100}
    return a, b, residuals


def save(a: float, b: float, residuals: dict[str, list[float]], path: str | Path | None = None) -> Path:
    p = Path(path) if path is not None else DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"a": round(a, 4), "b": round(b, 4), "residuals": residuals}))
    return p
