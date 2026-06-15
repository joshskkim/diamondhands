"""Closed-form match simulator checks against known tennis-probability values."""
import math

from ingester.tennis.match_sim import (
    game_win_prob,
    match_outcome,
    set_win_prob,
    tiebreak_win_prob,
)


def test_game_win_prob_known_values():
    # Coin-flip serve -> coin-flip game.
    assert abs(game_win_prob(0.5) - 0.5) < 1e-9
    # Textbook hold probabilities (Barnett/O'Malley): 60% points -> ~0.736 holds,
    # 62% -> ~0.776.
    assert abs(game_win_prob(0.60) - 0.736) < 0.005
    assert abs(game_win_prob(0.62) - 0.776) < 0.005
    # Monotonic and bounded.
    assert game_win_prob(0.0) == 0.0
    assert game_win_prob(1.0) == 1.0
    assert game_win_prob(0.8) > game_win_prob(0.65) > game_win_prob(0.5)


def test_game_win_prob_amplifies_serve_edge():
    # The hierarchy amplifies a small per-point edge into a larger game edge.
    assert game_win_prob(0.55) > 0.55


def test_tiebreak_symmetry_and_monotonicity():
    # Equal servers -> 50/50 tiebreak.
    assert abs(tiebreak_win_prob(0.62, 0.62) - 0.5) < 1e-6
    # Stronger server (and weaker opponent serve) wins more tiebreaks.
    assert tiebreak_win_prob(0.70, 0.60) > 0.5
    assert tiebreak_win_prob(0.60, 0.70) < 0.5
    # Antisymmetry: swapping players reflects the probability.
    assert abs(tiebreak_win_prob(0.70, 0.60) + tiebreak_win_prob(0.60, 0.70) - 1.0) < 1e-6


def test_set_symmetry():
    assert abs(set_win_prob(0.62, 0.62) - 0.5) < 1e-6
    assert set_win_prob(0.68, 0.60) > 0.5


def test_match_bo5_amplifies_favorite_vs_bo3():
    # More sets reduce variance -> the favorite's match win prob rises in Bo5.
    p3 = match_outcome(0.66, 0.61, best_of=3)["p_win_a"]
    p5 = match_outcome(0.66, 0.61, best_of=5)["p_win_a"]
    assert p5 > p3 > 0.5


def test_match_summary_fields_sane():
    out = match_outcome(0.65, 0.62, best_of=3)
    assert 0.0 < out["p_win_a"] < 1.0
    assert 0.0 < out["prob_straight_sets"] < 1.0
    # A Bo3 match runs ~12-39 games; expect a sane mean.
    assert 12.0 < out["exp_total_games"] < 39.0


def test_equal_players_straight_sets_floor_bo3():
    # Two equal players: straight sets (2-0 or 0-2) happens half the time in Bo3.
    out = match_outcome(0.62, 0.62, best_of=3)
    assert abs(out["p_win_a"] - 0.5) < 1e-6
    assert abs(out["prob_straight_sets"] - 0.5) < 1e-6
    assert not math.isnan(out["exp_total_games"])
