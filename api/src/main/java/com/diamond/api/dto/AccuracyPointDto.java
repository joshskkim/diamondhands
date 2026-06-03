package com.diamond.api.dto;

/** One day's accuracy snapshot for a market (brier/baseline/ece are null for total_runs). */
public record AccuracyPointDto(
    String date,
    int n,
    Double brier,
    Double baselineBrier,
    Double ece) {}
