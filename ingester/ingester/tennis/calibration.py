"""Isotonic calibration of the tennis match-winner probability.

Mirrors the MLB projection/calibration.py loop (fit a monotonic predicted->observed
map from walk-forward predictions, store 101 grid values, apply with numpy.interp at
projection time). Single market here ('match_winner'); the surface-blended Elo is
already fairly well calibrated, so this is a light final polish.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

_GRID = np.linspace(0.0, 1.0, 101)
MARKET = "match_winner"
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "models" / "tennis_calibration.json"


class TennisCalibrator:
    """Applies a stored isotonic map to a match-winner probability."""

    def __init__(self, maps: dict[str, list[float]]):
        self._maps = {k: np.asarray(v, dtype=float) for k, v in maps.items() if v}

    @classmethod
    def load(cls, path: str | Path | None = None) -> "TennisCalibrator | None":
        p = Path(path) if path is not None else DEFAULT_PATH
        if not p.exists():
            return None
        maps = json.loads(p.read_text()).get("maps", {})
        return cls(maps) if maps else None

    def apply(self, prob: float | None, market: str = MARKET) -> float | None:
        if prob is None:
            return prob
        y = self._maps.get(market)
        if y is None:
            return prob
        return float(min(1.0, max(0.0, np.interp(prob, _GRID, y))))


def save_map(values: list[float], path: str | Path | None = None) -> Path:
    p = Path(path) if path is not None else DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"maps": {MARKET: values}}, indent=2))
    return p
