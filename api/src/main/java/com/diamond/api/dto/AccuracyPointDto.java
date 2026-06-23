package com.diamond.api.dto;

/** One day's accuracy snapshot for a market (binary metrics are null for total_runs). */
public record AccuracyPointDto(
    String date,
    int n,
    Double brier,
    Double baselineBrier,
    Double ece,
    Double logLoss,
    Double sharpness) {}
