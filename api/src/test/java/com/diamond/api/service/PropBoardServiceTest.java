package com.diamond.api.service;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Unit tests for the prop board's sim-blend math (the pure helper that mixes the
 * Monte-Carlo simulator's per-batter estimate into the closed-form model probability).
 */
class PropBoardServiceTest {

    private static final double EPS = 1e-9;

    @Test
    void simBlend_returnsModelProb_whenSimMissing() {
        // Padded lineup slots have no sim estimate — must fall back to the closed form.
        assertThat(PropBoardService.simBlend(0.62, null, 0.5)).isCloseTo(0.62, org.assertj.core.data.Offset.offset(EPS));
    }

    @Test
    void simBlend_returnsModelProb_whenWeightZero() {
        // Default (unfit) weight is 0 → board behaves exactly as before the blend existed.
        assertThat(PropBoardService.simBlend(0.62, 0.40, 0.0)).isCloseTo(0.62, org.assertj.core.data.Offset.offset(EPS));
    }

    @Test
    void simBlend_returnsModelProb_whenWeightNegative() {
        assertThat(PropBoardService.simBlend(0.62, 0.40, -0.3)).isCloseTo(0.62, org.assertj.core.data.Offset.offset(EPS));
    }

    @Test
    void simBlend_weightsTowardSim() {
        // 0.25 weight pulls a 0.60 model prob a quarter of the way to the sim's 0.40.
        assertThat(PropBoardService.simBlend(0.60, 0.40, 0.25))
            .isCloseTo(0.55, org.assertj.core.data.Offset.offset(EPS));
    }

    @Test
    void simBlend_fullWeightReturnsSim() {
        assertThat(PropBoardService.simBlend(0.60, 0.40, 1.0))
            .isCloseTo(0.40, org.assertj.core.data.Offset.offset(EPS));
    }
}
