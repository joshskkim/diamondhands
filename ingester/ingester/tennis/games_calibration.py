"""Linear calibration of the total-games projection.

The closed-form i.i.d. simulator over-counts games (~+2): real sets break a bit
more often than independent points imply. We learn an affine map actual ≈ a +
b*predicted from walk-forward predictions and apply it to the whole games
distribution (each sample -> a + b*sample), which fixes both the displayed
expected games and the over/under tail probabilities.
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "models" / "tennis_games_calibration.json"


class GamesCalibrator:
    def __init__(self, a: float, b: float):
        self.a = a
        self.b = b

    @classmethod
    def load(cls, path: str | Path | None = None) -> "GamesCalibrator | None":
        p = Path(path) if path is not None else DEFAULT_PATH
        if not p.exists():
            return None
        d = json.loads(p.read_text())
        return cls(float(d["a"]), float(d["b"]))

    def mean(self, x: float) -> float:
        return self.a + self.b * x

    def samples(self, samples: tuple[int, ...]) -> list[float]:
        return [self.a + self.b * s for s in samples]


def fit_linear(predicted: list[float], actual: list[int]) -> tuple[float, float]:
    """Least-squares a, b for actual ≈ a + b*predicted (no numpy dependency)."""
    n = len(predicted)
    mx = sum(predicted) / n
    my = sum(actual) / n
    sxx = sum((x - mx) ** 2 for x in predicted)
    sxy = sum((x - mx) * (y - my) for x, y in zip(predicted, actual))
    b = sxy / sxx if sxx else 1.0
    a = my - b * mx
    return (a, b)


def save(a: float, b: float, path: str | Path | None = None) -> Path:
    p = Path(path) if path is not None else DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"a": round(a, 4), "b": round(b, 4)}, indent=2))
    return p
