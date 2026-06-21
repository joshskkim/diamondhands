package com.diamond.api.dto;

/**
 * One batter's posted over-price for a prop market (hit / hr) — the best price
 * across the books we ingest (FanDuel / DraftKings / Fanatics). Used to attach a real
 * sportsbook number to the model's Best Bets picks. Keyed by gameId + playerId +
 * market so the client can join it to a projection row.
 */
public record BatterPropOddsDto(
    long gameId,
    int playerId,
    String market,
    Double line,
    String book,
    Integer priceAmerican,
    Double priceDecimal
) {}
