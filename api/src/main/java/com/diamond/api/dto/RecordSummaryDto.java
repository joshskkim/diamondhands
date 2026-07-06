package com.diamond.api.dto;

/**
 * Aggregate win/loss record for a slice of graded Model's Picks (overall, one market, one tier,
 * or one book). Flat 1-unit stake at the recorded best price: a win returns {@code decimal − 1}
 * units, a loss {@code −1}, a push {@code 0}. {@code winPct} is over decided picks only (wins +
 * losses, excluding pushes); {@code roiPct} is units ÷ all settled non-void picks (wins + losses
 * + pushes). The CLV trio covers only the slice's picks with a captured closing quote (see
 * {@link TrackRecordResponse}); all three are null when the slice has none.
 */
public record RecordSummaryDto(
    String label,
    int n,          // settled non-void picks (wins + losses + pushes)
    int wins,
    int losses,
    int pushes,
    double winPct,  // wins / (wins + losses), 0 when none decided
    double units,   // net units at flat 1u stakes
    double roiPct,  // units / n * 100
    Integer clvN,   // picks in this slice with a closing quote, or null when none
    Double clvRate, // share of clvN with strictly positive CLV, or null
    Double avgClv   // mean CLV over clvN, or null
) {}
