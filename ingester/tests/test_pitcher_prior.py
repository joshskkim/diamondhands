"""Unit tests for the Lever 4 pitcher Marcel true-talent prior."""
from __future__ import annotations

import unittest

from ingester.projection.constants import (
    LEAGUE_BB_PER_PA,
    LEAGUE_HIT_PER_PA,
    LEAGUE_HR_PER_PA,
    LEAGUE_K_PER_PA,
)
from ingester.projection.pitcher_prior import (
    PitcherSeasonLine,
    compute_pitcher_marcel_prior,
)

LG = dict(
    league_k_rate=LEAGUE_K_PER_PA,
    league_bb_rate=LEAGUE_BB_PER_PA,
    league_hr_per_pa=LEAGUE_HR_PER_PA,
    league_hits_per_pa=LEAGUE_HIT_PER_PA,
)


def _line(bf, k_rate, bb_rate, hr_rate, hits_rate):
    return PitcherSeasonLine(
        bf=bf,
        k=round(k_rate * bf),
        bb=round(bb_rate * bf),
        hr=round(hr_rate * bf),
        hits=round(hits_rate * bf),
    )


class TestPitcherMarcelPrior(unittest.TestCase):
    def test_none_without_prior_seasons(self) -> None:
        self.assertIsNone(compute_pitcher_marcel_prior({}, 2026, **LG))
        # A season outside the 3-year window doesn't count.
        far = {2020: _line(500, 0.30, 0.07, 0.05, 0.22)}
        self.assertIsNone(compute_pitcher_marcel_prior(far, 2026, **LG))

    def test_rates_between_own_and_league(self) -> None:
        seasons = {y: _line(500, 0.30, 0.05, 0.050, 0.21) for y in (2023, 2024, 2025)}
        p = compute_pitcher_marcel_prior(seasons, 2026, **LG)
        assert p is not None
        # K (high own rate) stays above league; regressed but only lightly.
        self.assertGreater(p.k_rate, LEAGUE_K_PER_PA)
        self.assertLess(p.k_rate, 0.30)
        # HR sits between own and league too.
        self.assertGreater(p.hr_per_pa, LEAGUE_HR_PER_PA)
        self.assertLess(p.hr_per_pa, 0.050)

    def test_hr_regresses_harder_than_k(self) -> None:
        """HR's heavier regression constant pulls it toward league more than K."""
        seasons = {y: _line(500, 0.30, 0.05, 0.050, 0.21) for y in (2023, 2024, 2025)}
        p = compute_pitcher_marcel_prior(seasons, 2026, **LG)
        assert p is not None
        k_frac = (0.30 - p.k_rate) / (0.30 - LEAGUE_K_PER_PA)
        hr_frac = (0.050 - p.hr_per_pa) / (0.050 - LEAGUE_HR_PER_PA)
        self.assertGreater(hr_frac, k_frac)

    def test_recency_weighting(self) -> None:
        """Closer seasons dominate: result leans toward the target-1 rate."""
        seasons = {
            2025: _line(500, 0.32, 0.05, 0.04, 0.21),  # recent, high K
            2024: _line(500, 0.22, 0.05, 0.04, 0.21),
            2023: _line(500, 0.22, 0.05, 0.04, 0.21),
        }
        p = compute_pitcher_marcel_prior(seasons, 2026, **LG)
        seasons_flat = {y: _line(500, 0.32, 0.05, 0.04, 0.21) for y in (2023, 2024, 2025)}
        p_flat = compute_pitcher_marcel_prior(seasons_flat, 2026, **LG)
        assert p is not None and p_flat is not None
        # Both have one+ high-K seasons; the all-high one must project higher K.
        self.assertGreater(p_flat.k_rate, p.k_rate)
        self.assertGreater(p.proj_bf, 0)


if __name__ == "__main__":
    unittest.main()
