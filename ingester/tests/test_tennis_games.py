"""Total-games Monte-Carlo distribution + the empirical games model."""
from ingester.tennis.games_calibration import GamesCalibrator, fit_games_model, fit_linear
from ingester.tennis.match_sim import games_stats, p_total_over


def test_games_stats_sane_range():
    s = games_stats(0.65, 0.62, best_of=3, n_sims=1500)
    assert 18 < s["mean"] < 30
    assert s["std"] > 1.0
    assert games_stats(0.65, 0.62, best_of=5, n_sims=1500)["mean"] > s["mean"]


def test_p_total_over_monotonic_decreasing():
    hi = p_total_over(0.64, 0.63, 18.5, best_of=3, n_sims=1500)
    mid = p_total_over(0.64, 0.63, 22.5, best_of=3, n_sims=1500)
    lo = p_total_over(0.64, 0.63, 28.5, best_of=3, n_sims=1500)
    assert hi > mid > lo
    assert 0.0 <= lo and hi <= 1.0


def test_fit_linear_recovers_coefficients():
    preds = [10.0, 20.0, 30.0, 40.0]
    actual = [3 + 0.8 * p for p in preds]
    a, b = fit_linear(preds, actual)
    assert abs(a - 3.0) < 1e-6 and abs(b - 0.8) < 1e-6


def test_games_calibrator_mean_affine():
    cal = GamesCalibrator(3.3, 0.8)
    assert abs(cal.mean(25.0) - (3.3 + 0.8 * 25.0)) < 1e-9
    # No residuals fitted -> no distribution.
    assert cal.p_over(25.0, 3, 22.5) is None


def test_games_model_distribution_and_monotonic_p_over():
    # Synthetic: actual ≈ predicted (a≈0,b≈1) with a spread of residuals.
    records = [(22.0, 22 + r, 3) for r in range(-6, 7)] * 10
    records += [(38.0, 38 + r, 5) for r in range(-8, 9)] * 10
    a, b, residuals = fit_games_model(records)
    cal = GamesCalibrator(a, b, {int(k): v for k, v in residuals.items()})
    # p_over decreases as the line rises, and is ~0.5 at the mean.
    assert cal.p_over(22.0, 3, 16.5) > cal.p_over(22.0, 3, 22.0) > cal.p_over(22.0, 3, 28.5)
    assert abs(cal.p_over(22.0, 3, cal.mean(22.0)) - 0.5) < 0.15
    # PIT of the central actual is near 0.5.
    assert abs(cal.pit(22.0, 3, round(cal.mean(22.0))) - 0.5) < 0.15
