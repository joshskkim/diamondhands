package com.diamond.api.dto;

/** One bookmaker's price for a single line (american + derived decimal/implied). */
public record BookPriceDto(
    String book,
    int priceAmerican,
    double priceDecimal,
    double impliedProb
) {}
