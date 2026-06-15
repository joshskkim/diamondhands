package com.diamond.api.service;

import com.diamond.api.dto.TennisEvDto;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/** De-vig + EV selection for tennis match-winner odds. */
class TennisEvTest {

    @Test
    void picksPositiveEdgeSideAndComputesEv() {
        // Model: A wins 32% (B 68%). Best prices: A +125 (dec 2.25, imp .444),
        // B -150 (dec 1.69, imp .592). De-vig fair: A .429 / B .571 -> bet B.
        TennisEvDto best = TennisEv.bestPlay(
            0.32,
            125, 2.25, 0.444, "fanduel", "Carlos Alcaraz",
            -150, 1.69, 0.592, "draftkings", "Jannik Sinner");

        assertThat(best).isNotNull();
        assertThat(best.side()).isEqualTo("player_b");
        assertThat(best.playerName()).isEqualTo("Jannik Sinner");
        assertThat(best.fairProb()).isCloseTo(0.5714, org.assertj.core.data.Offset.offset(0.002));
        assertThat(best.edgePct()).isGreaterThan(0.0);              // 68% model vs 57% fair
        assertThat(best.evPct()).isCloseTo(14.92, org.assertj.core.data.Offset.offset(0.5));
    }

    @Test
    void returnsNullWhenProjectionOrPricesMissing() {
        assertThat(TennisEv.bestPlay(null, 100, 2.0, 0.5, "x", "A", -110, 1.9, 0.52, "y", "B")).isNull();
        assertThat(TennisEv.bestPlay(0.5, null, null, null, null, "A", -110, 1.9, 0.52, "y", "B")).isNull();
    }

    @Test
    void exactlyOneSideHasNonNegativeEdge() {
        // Model agrees with the favorite -> best play is the favorite (player_a).
        TennisEvDto best = TennisEv.bestPlay(
            0.75,
            -200, 1.50, 0.667, "a", "Fav",
            170, 2.70, 0.370, "b", "Dog");
        assertThat(best.side()).isEqualTo("player_a");
        assertThat(best.edgePct()).isGreaterThan(0.0);
    }
}
