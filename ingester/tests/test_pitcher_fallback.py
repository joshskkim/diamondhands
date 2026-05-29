"""Tests for resolve_pitcher_skill three-tier fallback."""
from __future__ import annotations

import unittest

from ingester.projection.constants import MIN_BF_PITCHER_HANDEDNESS
from ingester.projection.pitcher_adj import (
    LEAGUE_AVG_PITCHER,
    PitcherHandSplit,
    compute_pitcher_adjustments,
    resolve_pitcher_skill,
)


def _split(hand: str, bf: int) -> PitcherHandSplit:
    return PitcherHandSplit(
        vs_handedness=hand,
        batters_faced=bf,
        hits_per_pa=0.200,
        hr_per_pa=0.025,
        k_rate=0.280,
    )


class TestResolvePitcherSkillTier1(unittest.TestCase):
    def test_matchup_split_sufficient_bf(self) -> None:
        """Tier 1: vs-hand split with BF ≥ threshold → quality 'matchup'."""
        splits = [_split("L", 100), _split("R", 80)]
        split, quality = resolve_pitcher_skill(splits, "L")
        self.assertEqual(quality, "matchup")
        self.assertEqual(split.vs_handedness, "L")
        self.assertEqual(split.batters_faced, 100)

    def test_matchup_righty_batter(self) -> None:
        splits = [_split("L", 60), _split("R", 55)]
        split, quality = resolve_pitcher_skill(splits, "R")
        self.assertEqual(quality, "matchup")
        self.assertEqual(split.vs_handedness, "R")

    def test_exactly_at_threshold(self) -> None:
        """BF == MIN_BF_PITCHER_HANDEDNESS should qualify for Tier 1."""
        splits = [_split("L", MIN_BF_PITCHER_HANDEDNESS)]
        split, quality = resolve_pitcher_skill(splits, "L")
        self.assertEqual(quality, "matchup")


class TestResolvePitcherSkillTier2(unittest.TestCase):
    def test_thin_matchup_but_overall_sufficient(self) -> None:
        """Tier 2: matchup BF < threshold but combined total BF ≥ threshold."""
        splits = [_split("L", 20), _split("R", 60)]
        split, quality = resolve_pitcher_skill(splits, "L")
        self.assertEqual(quality, "overall")
        self.assertEqual(split.vs_handedness, "*")

    def test_no_matchup_split_but_other_hand_sufficient(self) -> None:
        """Tier 2: only one-hand data available, no split for batter's hand."""
        splits = [_split("R", 80)]  # batter bats L, no L split
        split, quality = resolve_pitcher_skill(splits, "L")
        self.assertEqual(quality, "overall")
        # combined BF = 80 ≥ 50, so tier 2
        self.assertEqual(split.vs_handedness, "*")

    def test_overall_is_bf_weighted_average(self) -> None:
        """Tier 2 overall split has BF-weighted rates."""
        splits = [
            PitcherHandSplit("L", batters_faced=40, hits_per_pa=0.3, hr_per_pa=0.05, k_rate=0.20),
            PitcherHandSplit("R", batters_faced=60, hits_per_pa=0.2, hr_per_pa=0.03, k_rate=0.30),
        ]
        split, quality = resolve_pitcher_skill(splits, "L")
        self.assertEqual(quality, "overall")
        expected_hits = (0.3 * 40 + 0.2 * 60) / 100
        self.assertAlmostEqual(split.hits_per_pa, expected_hits, places=6)


class TestResolvePitcherSkillTier3(unittest.TestCase):
    def test_empty_splits(self) -> None:
        """Tier 3: no splits at all → league avg."""
        split, quality = resolve_pitcher_skill([], "R")
        self.assertEqual(quality, "league_avg")
        self.assertIs(split, LEAGUE_AVG_PITCHER)

    def test_insufficient_total_bf(self) -> None:
        """Tier 3: total BF below threshold → league avg."""
        splits = [_split("L", 20), _split("R", 15)]
        split, quality = resolve_pitcher_skill(splits, "L")
        self.assertEqual(quality, "league_avg")
        self.assertIs(split, LEAGUE_AVG_PITCHER)

    def test_matchup_only_below_threshold_no_other_hand(self) -> None:
        """Single thin split below combined threshold → league avg."""
        splits = [_split("L", MIN_BF_PITCHER_HANDEDNESS - 1)]
        split, quality = resolve_pitcher_skill(splits, "L")
        self.assertEqual(quality, "league_avg")


class TestLeagueAvgPitcherMultipliers(unittest.TestCase):
    def test_unit_multipliers(self) -> None:
        """LEAGUE_AVG_PITCHER → hit/hr/k multipliers all ≈ 1.0."""
        adj = compute_pitcher_adjustments(LEAGUE_AVG_PITCHER)
        self.assertAlmostEqual(adj.hit, 1.0, places=3)
        self.assertAlmostEqual(adj.hr, 1.0, places=3)
        self.assertAlmostEqual(adj.k, 1.0, places=3)


if __name__ == "__main__":
    unittest.main()
