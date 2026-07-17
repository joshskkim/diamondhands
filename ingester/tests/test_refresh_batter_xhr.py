"""Unit tests for the hand-split xHR EB shrink (pure, no DB / no model)."""
from __future__ import annotations

from ingester.commands.refresh_batter_xhr import XHR_REGRESSION_BIP, _eb_shrink


def test_shrink_toward_target():
    # A hand's raw rate blends toward the target (the batter's own overall xHR).
    raw, target = 0.10, 0.04
    out = _eb_shrink(raw, n=XHR_REGRESSION_BIP, target=target)
    assert out == (raw + target) / 2  # equal n and k → midpoint


def test_thin_sample_reverts_to_target():
    # Almost no samples → dominated by the target (own overall power), not the raw hand.
    out = _eb_shrink(0.20, n=1, target=0.05)
    assert abs(out - 0.05) < 0.005


def test_large_sample_stays_near_raw():
    out = _eb_shrink(0.12, n=2000, target=0.05)
    assert abs(out - 0.12) < 0.005


def test_target_recovers_when_raw_equals_target():
    assert abs(_eb_shrink(0.06, n=137, target=0.06) - 0.06) < 1e-9
