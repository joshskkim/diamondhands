package com.diamond.api.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

import org.junit.jupiter.api.Test;

class OddsMathTest {

    @Test
    void americanToDecimal_positive() {
        assertThat(OddsMath.americanToDecimal(100)).isEqualTo(2.0);
        assertThat(OddsMath.americanToDecimal(120)).isEqualTo(2.2);
        assertThat(OddsMath.americanToDecimal(0)).isEqualTo(1.0);
    }

    @Test
    void americanToDecimal_negative() {
        assertThat(OddsMath.americanToDecimal(-100)).isEqualTo(2.0);
        assertThat(OddsMath.americanToDecimal(-150)).isCloseTo(1.6667, within(1e-4));
        assertThat(OddsMath.americanToDecimal(-110)).isCloseTo(1.9091, within(1e-4));
    }

    @Test
    void ev_isReturnPerUnit() {
        // 55% at +100: 0.55 * 2.0 - 1 = +0.10
        assertThat(OddsMath.ev(0.55, 2.0)).isCloseTo(0.10, within(1e-9));
        // fair coin at -110 loses the vig
        assertThat(OddsMath.ev(0.50, OddsMath.americanToDecimal(-110))).isLessThan(0.0);
        assertThat(OddsMath.ev(null, 2.0)).isNull();
    }

    @Test
    void fairShare_removesVig() {
        // -110/-110 two-way: each side implied ~0.5238, fair = exactly 0.5
        double implied = 1.0 / OddsMath.americanToDecimal(-110);
        Double fair = OddsMath.fairShare(implied, implied * 2);
        assertThat(fair).isCloseTo(0.5, within(1e-9));
    }

    @Test
    void fairShare_nullWhenNotDeviggable() {
        assertThat(OddsMath.fairShare(null, 1.0)).isNull();
        assertThat(OddsMath.fairShare(0.52, null)).isNull();
        assertThat(OddsMath.fairShare(0.52, 0.0)).isNull();
    }
}
