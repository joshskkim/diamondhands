"""Load saved XGBoost market models and score a feature row at projection time.

ModelBundle.load() returns None when no models are present, so callers fall back to the
mechanistic model. predict() takes the dict from features.build_feature_row and returns
per-market probabilities in the same feature order the models were trained on.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import xgboost as xgb

from ingester.ml.dataset import MODELS_DIR

_MARKETS = ("h1", "h2", "hr", "k")


class ModelBundle:
    def __init__(self, boosters: dict[str, xgb.Booster], features: list[str], blend: dict | None = None):
        self.boosters = boosters
        self.features = features
        # blend[market] = weight on the MECHANISTIC probability (None => pure xgb).
        self.blend = blend

    @classmethod
    def load(cls, models_dir: Path = MODELS_DIR, blend: bool = False) -> "ModelBundle | None":
        import json
        spec = models_dir / "feature_spec.json"
        if not spec.exists():
            return None
        features = json.loads(spec.read_text())["features"]
        boosters: dict[str, xgb.Booster] = {}
        for m in _MARKETS:
            path = models_dir / f"{m}.json"
            if path.exists():
                b = xgb.Booster()
                b.load_model(str(path))
                boosters[m] = b
        if not boosters:
            return None
        weights = None
        if blend:
            bpath = models_dir / "blend.json"
            if not bpath.exists():
                return None
            weights = json.loads(bpath.read_text())
        return cls(boosters, features, weights)

    def predict(self, feature_row: dict) -> dict[str, float]:
        """Return {market: probability} for the markets this bundle has models for."""
        x = np.array(
            [[_f(feature_row.get(name)) for name in self.features]], dtype="float64"
        )
        dm = xgb.DMatrix(x, feature_names=self.features)
        return {m: float(b.predict(dm)[0]) for m, b in self.boosters.items()}


def _f(v) -> float:
    return np.nan if v is None else float(v)
