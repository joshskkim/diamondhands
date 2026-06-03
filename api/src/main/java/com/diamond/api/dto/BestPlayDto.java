package com.diamond.api.dto;

/** One model-edged selection for the "Today's Best Lines" board (GET /api/odds/best). */
public record BestPlayDto(
    long gameId,
    String matchup,
    String market,
    String selection,
    Double line,
    String bestBook,
    int priceAmerican,
    double priceDecimal,
    double modelProb,
    double impliedProb,
    double evPct,
    Integer playerId,
    String playerName
) {}
