"""Serve-rate projection helpers for the ace / double-fault prop model."""
from ingester.tennis.serve_rates import project_aces, project_dfs, serve_points


def test_serve_points_scales_with_games():
    assert serve_points(20) < serve_points(30)
    # ~half the games, ~6 points each -> a Bo3 (~22 games) is ~60-70 serve points.
    assert 55 < serve_points(22) < 80


def test_project_aces_opponent_adjustment():
    league = {"ace_rate": 0.08, "df_rate": 0.03}
    big_server = {"ace_rate": 0.15, "df_rate": 0.03, "ace_against": 0.08}
    weak_server = {"ace_rate": 0.04, "df_rate": 0.03, "ace_against": 0.08}
    easy_to_ace = {"ace_rate": 0.06, "df_rate": 0.03, "ace_against": 0.12}   # gets aced a lot
    hard_to_ace = {"ace_rate": 0.06, "df_rate": 0.03, "ace_against": 0.05}

    # Big server projects more aces than a weak server vs the same returner.
    assert project_aces(big_server, hard_to_ace, league, 24) > project_aces(weak_server, hard_to_ace, league, 24)
    # Same server projects more aces against an easy-to-ace returner.
    assert project_aces(big_server, easy_to_ace, league, 24) > project_aces(big_server, hard_to_ace, league, 24)


def test_project_dfs_scales_with_rate_and_games():
    s = {"ace_rate": 0.1, "df_rate": 0.05, "ace_against": 0.08}
    assert project_dfs(s, 30) > project_dfs(s, 20)
    assert project_dfs({**s, "df_rate": 0.08}, 24) > project_dfs(s, 24)
