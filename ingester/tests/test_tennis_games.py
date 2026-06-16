"""Total-games Monte-Carlo distribution + affine games calibration."""
from ingester.tennis.games_calibration import GamesCalibrator, fit_linear
from ingester.tennis.match_sim import games_stats, p_total_over


def test_games_stats_sane_range():
    s = games_stats(0.65, 0.62, best_of=3, n_sims=1500)
    assert 18 < s["mean"] < 30          # a Bo3 match
    assert s["std"] > 1.0
    # Bo5 plays more games than Bo3 for the same servers.
    assert games_stats(0.65, 0.62, best_of=5, n_sims=1500)["mean"] > s["mean"]


def test_p_total_over_monotonic_decreasing():
    hi = p_total_over(0.64, 0.63, 18.5, best_of=3, n_sims=1500)
    mid = p_total_over(0.64, 0.63, 22.5, best_of=3, n_sims=1500)
    lo = p_total_over(0.64, 0.63, 28.5, best_of=3, n_sims=1500)
    assert hi > mid > lo
    assert 0.0 <= lo and hi <= 1.0


def test_fit_linear_recovers_coefficients():
    preds = [10.0, 20.0, 30.0, 40.0]
    actual = [3 + 0.8 * p for p in preds]  # a=3, b=0.8
    a, b = fit_linear(preds, [round(v) if False else v for v in actual])  # floats ok
    assert abs(a - 3.0) < 1e-6
    assert abs(b - 0.8) < 1e-6


def test_games_calibrator_affine():
    cal = GamesCalibrator(3.3, 0.8)
    assert abs(cal.mean(25.0) - (3.3 + 0.8 * 25.0)) < 1e-9
    assert cal.samples((10, 20)) == [3.3 + 0.8 * 10, 3.3 + 0.8 * 20]
