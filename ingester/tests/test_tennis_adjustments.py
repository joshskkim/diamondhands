"""Refinement-lever feature functions, logit apply, and the fatigue tracker."""
from datetime import date

from ingester.tennis.adjustments import (
    FatigueTracker,
    age_feature,
    apply_levers,
    backhand_feature,
    court_speed_feature,
    fatigue_feature,
    lefty_feature,
)


def test_court_speed_feature_favors_better_server_on_fast_court():
    # Fast court (z>0), A the better server -> positive (favors A).
    assert court_speed_feature(0.70, 0.60, 1.5) > 0
    # Slow court flips the sign.
    assert court_speed_feature(0.70, 0.60, -1.5) < 0
    # Missing inputs -> neutral.
    assert court_speed_feature(None, 0.6, 1.0) == 0.0
    assert court_speed_feature(0.7, 0.6, None) == 0.0


def test_fatigue_feature_penalizes_more_loaded_player():
    # A more loaded than B -> negative (favors B).
    assert fatigue_feature(40, 10) < 0
    assert fatigue_feature(10, 40) > 0
    assert fatigue_feature(20, 20) == 0.0


def test_lefty_feature():
    assert lefty_feature("L", "R") == 1.0
    assert lefty_feature("R", "L") == -1.0
    assert lefty_feature("R", "R") == 0.0
    assert lefty_feature("L", "L") == 0.0


def test_age_feature_favors_nearer_peak():
    # a at peak (~24.5) vs an older b -> positive (favors a).
    assert age_feature(25, 35) > 0
    assert age_feature(35, 25) < 0
    # A young riser vs a peak player is slightly disfavored by the curve.
    assert age_feature(19, 25) < 0
    assert age_feature(None, 25) == 0.0


def test_backhand_feature():
    # b is the one-hander (1) vs two-hander a (2) -> +1 (favors a).
    assert backhand_feature(2, 1) == 1.0
    assert backhand_feature(1, 2) == -1.0
    assert backhand_feature(2, 2) == 0.0
    assert backhand_feature(None, 1) == 0.0


def test_apply_levers_zero_beta_is_identity():
    assert abs(apply_levers(0.62, court_feat=1.0, court_beta=0.0) - 0.62) < 1e-9


def test_apply_levers_moves_probability_in_feature_direction():
    base = 0.50
    up = apply_levers(base, court_feat=0.2, court_beta=2.0)
    down = apply_levers(base, court_feat=-0.2, court_beta=2.0)
    assert up > base > down
    # Symmetric around 0.5 for opposite features.
    assert abs((up - 0.5) - (0.5 - down)) < 1e-9


def test_fatigue_tracker_counts_prior_load_within_window():
    # Queried chronologically (as in the backtest: load BEFORE adding each match).
    ft = FatigueTracker(window_days=14)
    p = "X"
    assert ft.load(p, date(2025, 1, 1)) == 0.0       # no history yet
    ft.add(p, date(2025, 1, 1), 20)
    ft.add(p, date(2025, 1, 5), 18)
    # As of Jan 10: the Jan 1 + Jan 5 matches count (38).
    assert ft.load(p, date(2025, 1, 10)) == 38.0
    ft.add(p, date(2025, 3, 1), 22)                  # well outside the Jan window
    # As of March 1: only the March match is within 14 days.
    assert ft.load(p, date(2025, 3, 1)) == 22.0
    # Unknown player -> 0.
    assert ft.load("Y", date(2025, 1, 10)) == 0.0
