package com.diamond.api.dto;

/** One book's match-winner price for one side. */
public record TennisQuoteDto(
    String side,            // "player_a" | "player_b"
    String bookmaker,
    Integer priceAmerican,
    Double priceDecimal,
    Double impliedProb
) {}
