package com.diamond.api.dto;

/** One point on the cumulative-units equity curve: the running total through {@code date}. */
public record EquityPointDto(
    String date,
    double cumUnits,
    int cumWins,
    int cumLosses
) {}
