package com.diamond.api.service;

import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

/**
 * Reading P(over) off a stored workload K/outs ladder, including the off-grid
 * interpolation that keeps a book line between two materialized grid points from blanking.
 */
class PropDistributionTest {

    // A monotone (decreasing in the line) ladder, as stored in the workload jsonb.
    private static final Map<String, Double> LADDER =
        Map.of("3.5", 0.80, "4.5", 0.60, "5.5", 0.40, "6.5", 0.20);

    @Test
    void exactGridHitReturnsStoredProb() {
        assertThat(PropDistribution.ladderProb(LADDER, 5.5)).isEqualTo(0.40);
    }

    @Test
    void offGridLineInterpolatesBetweenNeighbours() {
        // 5.0 sits halfway between 4.5 (0.60) and 5.5 (0.40) -> 0.50.
        assertThat(PropDistribution.ladderProb(LADDER, 5.0)).isCloseTo(0.50, within(1e-9));
        // 4.25 -> a quarter of the way from 3.5 (0.80) toward 4.5 (0.60): 0.80 - 0.75*0.20.
        assertThat(PropDistribution.ladderProb(LADDER, 4.25)).isCloseTo(0.65, within(1e-9));
    }

    @Test
    void outsideMaterializedRangeIsNull() {
        assertThat(PropDistribution.ladderProb(LADDER, 2.5)).isNull(); // below min
        assertThat(PropDistribution.ladderProb(LADDER, 7.5)).isNull(); // above max
    }

    @Test
    void nullOrEmptyLadderIsNull() {
        Map<String, Double> empty = Map.of();
        assertThat(PropDistribution.ladderProb((Map<String, Double>) null, 5.5)).isNull();
        assertThat(PropDistribution.ladderProb(empty, 5.5)).isNull();
    }
}
