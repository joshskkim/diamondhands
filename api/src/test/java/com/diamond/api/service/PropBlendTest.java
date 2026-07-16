package com.diamond.api.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.api.Assertions.within;

import com.diamond.api.repository.ClearRateRepository.ClearRates;
import org.junit.jupiter.api.Test;

/**
 * The two-stage shrinkage that stops the adjustment chain from advertising probabilities a
 * player's own track record contradicts: (1) the season clear-rate is stabilized toward the
 * league rate by PRIOR_N phantom games, (2) the model prob is pulled toward that target with
 * weight growing in evidence. Blending is only legitimate at the canonical line the clear
 * rate measures — everything else must pass through untouched.
 */
class PropBlendTest {

    // Mirror PropBlend's constants: the arithmetic below is the spec, not a copy of the code.
    private static final int SHRINK_K = 60;
    private static final int PRIOR_N = 25;

    private static ClearRates ratesWith(Double hrSeason, int nSeason) {
        return new ClearRates(null, null, null, null, null, null,
            null, hrSeason, null, null, null, null, nSeason, 0);
    }

    @Test
    void noEvidence_regressesTowardLeagueRateOnly() {
        // No season rate: empirical target = league rate, weight = PRIOR_N/(PRIOR_N+SHRINK_K).
        double model = 0.85, league = 0.15;
        double w = PRIOR_N / (double) (PRIOR_N + SHRINK_K);
        double expected = w * league + (1 - w) * model;
        assertThat(PropBlend.blend(model, null, null, league)).isCloseTo(expected, within(1e-12));
    }

    @Test
    void strongEvidence_dominatesTheModel() {
        // 120 games at a 10% clear rate: the blend must land far below a stacked 85% model prob.
        double blended = PropBlend.blend(0.85, 0.10, 120, 0.15);
        double weak = PropBlend.blend(0.85, 0.10, 5, 0.15);
        assertThat(blended).isLessThan(weak);       // more evidence pulls harder
        assertThat(blended).isLessThan(0.40);       // nowhere near the raw model claim
        // Exact two-stage arithmetic.
        double empirical = (120 * 0.10 + PRIOR_N * 0.15) / (120 + PRIOR_N);
        double w = (120 + PRIOR_N) / (double) (120 + PRIOR_N + SHRINK_K);
        assertThat(blended).isCloseTo(w * empirical + (1 - w) * 0.85, within(1e-12));
    }

    @Test
    void marketBlend_onlyAtTheCanonicalLine() {
        ClearRates rates = ratesWith(0.10, 120);
        // hr's canonical line is 0.5: blends.
        assertThat(PropBlend.blend("hr", 0.5, 0.85, rates)).isLessThan(0.85);
        // Off-canonical line: the clear rate measures a different event — pass through.
        assertThat(PropBlend.blend("hr", 1.5, 0.85, rates)).isEqualTo(0.85);
        // Markets without a clear rate (pitchers) pass through.
        assertThat(PropBlend.blend("pitcher_k", 5.5, 0.62, rates)).isEqualTo(0.62);
        // Null in, null out.
        assertThat(PropBlend.blend("hr", 0.5, null, rates)).isNull();
    }

    @Test
    void hrrSampleSize_usesTheBoxscoreOnlyCount() {
        // 90 games logged, but only 12 carry runs/rbi (post-V69 boxscore backfill): the
        // H+R+RBI blend must see n=12, not 90 — pre-backfill history can't pose as evidence.
        ClearRates rates = new ClearRates(null, null, null, null, null, null,
            null, null, null, null, null, 0.44, 90, 12);
        assertThat(PropBlend.nSeason("hrr", rates)).isEqualTo(12);
        assertThat(PropBlend.nSeason("tb", rates)).isEqualTo(90);
        assertThat(PropBlend.nSeason("hrr", null)).isNull();
    }

    @Test
    void leagueRate_throwsForUnknownMarket() {
        assertThat(PropBlend.leagueRate("hr")).isEqualTo(0.15);
        assertThatThrownBy(() -> PropBlend.leagueRate("nope"))
            .isInstanceOf(IllegalArgumentException.class);
    }
}
