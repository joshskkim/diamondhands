"""Per-market probability calibration (S3 — accuracy feedback loop).

The backtest reports where each market's predicted probabilities drift from the
realized rate (calibration buckets / ECE). This closes the loop: `fit-calibration`
learns an isotonic (monotonic) mapping predicted→calibrated for each market from a
backtest run's predictions-vs-actuals, and the projector applies it as a final
post-processing step so live probabilities match observed frequencies.

The fitted map is stored as 101 grid values (predicted 0.00..1.00 → calibrated) so
inference needs only numpy.interp — no sklearn dependency at projection time.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np

# Calibrated markets and the BatterProbabilities field each maps to.
MARKETS: tuple[str, ...] = ("h1", "h2", "hr", "k")
_FIELD = {
    "h1": "p_hit_1plus",
    "h2": "p_hit_2plus",
    "hr": "p_hr",
    "k": "p_k_1plus",
}
_GRID = np.linspace(0.0, 1.0, 101)
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "models" / "calibration.json"


class Calibrator:
    """Applies stored per-market isotonic maps to a BatterProjection's probabilities."""

    def __init__(self, maps: dict[str, list[float]]):
        self._maps = {m: np.asarray(v, dtype=float) for m, v in maps.items() if v}

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Calibrator | None":
        p = Path(path) if path is not None else DEFAULT_PATH
        if not p.exists():
            return None
        data = json.loads(p.read_text())
        maps = data.get("maps", {})
        return cls(maps) if maps else None

    def _cal(self, market: str, prob: float | None) -> float | None:
        if prob is None:
            return prob
        y = self._maps.get(market)
        if y is None:
            return prob
        return float(min(1.0, max(0.0, np.interp(prob, _GRID, y))))

    def apply(self, proj):
        """Return ``proj`` with each market probability passed through its calibration map.

        HIT (h1) is deliberately NOT calibrated here: a held-out backtest showed the
        per-player clear-rate blend beats the isotonic calibrator for hit and that stacking
        the two is worse than the blend alone, so the blend REPLACES calibration for h1
        (applied downstream from the raw prob — see runner._served_hit_prob / prop_blend).
        p_hit_1plus therefore stays raw through calibration; h2/hr/k are unchanged.
        """
        pr = proj.probabilities
        new = replace(
            pr,
            p_hit_2plus=self._cal("h2", pr.p_hit_2plus),
            p_hr=self._cal("hr", pr.p_hr),
            p_k_1plus=self._cal("k", pr.p_k_1plus),
        )
        return replace(proj, probabilities=new)


def fit_isotonic(predicted: list[float], actual: list[int]) -> list[float]:
    """Fit a monotonic predicted→observed map; return its values on the 0..1 grid."""
    from sklearn.isotonic import IsotonicRegression

    ir = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    ir.fit(np.asarray(predicted, dtype=float), np.asarray(actual, dtype=float))
    return [float(v) for v in ir.predict(_GRID)]


def save_maps(maps: dict[str, list[float]], path: str | Path | None = None) -> Path:
    p = Path(path) if path is not None else DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"maps": maps}, indent=2))
    return p
