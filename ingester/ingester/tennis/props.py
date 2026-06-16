"""Ace / double-fault prop distribution model.

The serve-rate model gives a count mean that can carry a small bias (stale/aggregated
rates), and the counts are overdispersed vs Poisson. So per market we store an affine
mean de-bias (a + b·raw_mean) plus a Negative-Binomial dispersion φ (variance = φ·μ),
and price P(over line) off the de-biased NB. Mirrors the games model.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from scipy.stats import nbinom

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "models" / "tennis_props.json"
MARKETS = ("aces", "dfs")


def _nb_params(mean: float, phi: float) -> tuple[float, float]:
    phi = max(phi, 1.01)
    r = mean / (phi - 1.0)
    return r, r / (r + mean)


def nb_p_over(mean: float, phi: float, line: float) -> float:
    if mean <= 0:
        return 0.0
    r, p = _nb_params(mean, phi)
    return float(1.0 - nbinom.cdf(math.floor(line), r, p))


class PropsModel:
    def __init__(self, params: dict[str, dict]):
        self.params = params   # {market: {"a","b","phi"}}

    @classmethod
    def load(cls, path: str | Path | None = None) -> "PropsModel | None":
        p = Path(path) if path is not None else DEFAULT_PATH
        if not p.exists():
            return None
        return cls(json.loads(p.read_text()).get("params", {}))

    def mean(self, market: str, raw_mean: float) -> float | None:
        m = self.params.get(market)
        return None if m is None else m["a"] + m["b"] * raw_mean

    def p_over(self, market: str, raw_mean: float, line: float) -> float | None:
        m = self.params.get(market)
        if m is None:
            return None
        return nb_p_over(m["a"] + m["b"] * raw_mean, m["phi"], line)


def _fit_linear(predicted: list[float], actual: list[float]) -> tuple[float, float]:
    n = len(predicted)
    mx = sum(predicted) / n
    my = sum(actual) / n
    sxx = sum((x - mx) ** 2 for x in predicted)
    sxy = sum((x - mx) * (y - my) for x, y in zip(predicted, actual))
    b = sxy / sxx if sxx else 1.0
    return (my - b * mx, b)


def fit_market(samples: list[tuple[int, float]]) -> dict:
    """samples: (actual, raw_mean) -> {a, b, phi} (affine de-bias + NB dispersion)."""
    a, b = _fit_linear([m for _y, m in samples], [float(y) for y, _m in samples])
    cal = [(y, a + b * m) for y, m in samples if a + b * m > 0]
    phi = max(1.05, sum((y - cm) ** 2 / cm for y, cm in cal) / len(cal)) if cal else 1.05
    return {"a": round(a, 4), "b": round(b, 4), "phi": round(phi, 3)}


def save(params: dict[str, dict], path: str | Path | None = None) -> Path:
    p = Path(path) if path is not None else DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"params": params}, indent=2))
    return p
