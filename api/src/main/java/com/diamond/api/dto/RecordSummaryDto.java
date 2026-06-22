package com.diamond.api.dto;

/**
 * Aggregate win/loss record for a slice of graded Model's Picks (overall, one market, or one
 * tier). Flat 1-unit stake at the recorded best price: a win returns {@code decimal − 1} units,
 * a loss {@code −1}, a push {@code 0}. {@code winPct} is over decided picks only (wins + losses,
 * excluding pushes); {@code roiPct} is units ÷ all settled non-void picks (wins + losses + pushes).
 */
public record RecordSummaryDto(
    String label,
    int n,          // settled non-void picks (wins + losses + pushes)
    int wins,
    int losses,
    int pushes,
    double winPct,  // wins / (wins + losses), 0 when none decided
    double units,   // net units at flat 1u stakes
    double roiPct   // units / n * 100
) {}
