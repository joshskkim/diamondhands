package com.diamond.api.ai;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * The bet stake is computed, never modelled — so it has to be exactly right and is unit-tested
 * against hand-worked values. Covers the edge cases the agent must never get wrong: no edge => no
 * stake, the fraction cap, and American/decimal conversion.
 */
class KellyCalculatorTest {

    private final KellyCalculator kelly = new KellyCalculator();

    @Test
    void quarterKellyOnAClearEdge() {
        // p=0.60 at +100 (decimal 2.0, b=1): full-Kelly f* = (0.6*2 - 1)/1 = 0.20.
        // quarter-Kelly of a 100-unit bankroll => 100 * 0.25 * 0.20 = 5 units.
        KellyCalculator.Sizing s = kelly.size(0.60, 2.0, 100, null, 0.25);
        assertThat(s.fullKelly()).isEqualTo(0.20);
        assertThat(s.stakeUnits()).isEqualTo(5.0);
    }

    @Test
    void noEdgeMeansNoStake() {
        // p=0.50 at +100 has zero edge => f* <= 0 => no bet.
        KellyCalculator.Sizing s = kelly.size(0.50, 2.0, 100, null, 0.25);
        assertThat(s.stakeUnits()).isEqualTo(0.0);
    }

    @Test
    void fractionIsCapped() {
        assertThat(KellyCalculator.clampFraction(0.9)).isEqualTo(KellyCalculator.MAX_KELLY_FRACTION);
        assertThat(KellyCalculator.clampFraction(-1)).isEqualTo(0.0);
    }

    @Test
    void americanToDecimal() {
        assertThat(KellyCalculator.americanToDecimal(100)).isEqualTo(2.0);
        assertThat(KellyCalculator.americanToDecimal(-110)).isCloseTo(1.909, org.assertj.core.data.Offset.offset(0.001));
        assertThat(KellyCalculator.americanToDecimal(150)).isEqualTo(2.5);
    }

    @Test
    void dollarStakeUsesUnitSize() {
        KellyCalculator.Sizing s = kelly.size(0.60, 2.0, 100, 20.0, 0.25);
        assertThat(s.stakeUsd()).isEqualTo(100.0); // 5 units * $20
    }
}
