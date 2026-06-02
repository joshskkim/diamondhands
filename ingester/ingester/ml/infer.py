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
_REGRESSORS = ("exp_hits", "exp_tb")


class ModelBundle:
    def __init__(self, boosters: dict[str, xgb.Booster], features: list[str],
                 blend: dict | None = None, regressors: dict | None = None):
        self.boosters = boosters
        self.features = features
        # blend[market] = weight on the MECHANISTIC probability (None => pure xgb).
        self.blend = blend
        # regressors: {exp_hits, exp_tb} boosters (None/empty => keep mechanistic counts).
        self.regressors = regressors or {}

    @classmethod
    def load(cls, models_dir: Path = MODELS_DIR, blend: bool = False) -> "ModelBundle | None":
        import json
        spec = models_dir / "feature_spec.json"
        if not spec.exists():
            return None
        features = json.loads(spec.read_text())["features"]

        def _load_boosters(names):
            out = {}
            for n in names:
                p = models_dir / f"{n}.json"
                if p.exists():
                    b = xgb.Booster()
                    b.load_model(str(p))
                    out[n] = b
            return out

        boosters = _load_boosters(_MARKETS)
        if not boosters:
            return None
        regressors = _load_boosters(_REGRESSORS)
        weights = None
        if blend:
            bpath = models_dir / "blend.json"
            if not bpath.exists():
                return None
            weights = json.loads(bpath.read_text())
        return cls(boosters, features, weights, regressors)

    def _dmatrix(self, feature_row: dict) -> xgb.DMatrix:
        x = np.array([[_f(feature_row.get(name)) for name in self.features]], dtype="float64")
        return xgb.DMatrix(x, feature_names=self.features)

    def predict(self, feature_row: dict) -> dict[str, float]:
        """Return {market: probability} for the markets this bundle has models for."""
        dm = self._dmatrix(feature_row)
        return {m: float(b.predict(dm)[0]) for m, b in self.boosters.items()}

    def predict_counts(self, feature_row: dict) -> dict[str, float] | None:
        """Return {exp_hits, exp_tb} from the regressors, or None if not loaded."""
        if not self.regressors:
            return None
        dm = self._dmatrix(feature_row)
        return {m: float(b.predict(dm)[0]) for m, b in self.regressors.items()}


def _f(v) -> float:
    return np.nan if v is None else float(v)
