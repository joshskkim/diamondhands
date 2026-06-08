package com.diamond.api.dto;

import java.util.List;

/**
 * Best available price for one side of one line, plus every book's price and our
 * model's view. modelProb/evPct are null for markets we don't model (e.g. pitcher props).
 * evPct = modelProb * bestPriceDecimal - 1 (expected value per $1 staked at the best line).
 * fairProb is the no-vig market probability for this side (this side's implied divided by
 * the two-sided implied sum); null when the opposite side isn't available to de-vig against.
 */
public record LineQuoteDto(
    String side,
    Double line,
    String bestBook,
    Integer priceAmerican,
    Double priceDecimal,
    Double impliedProb,
    Double fairProb,
    Double modelProb,
    Double evPct,
    List<BookPriceDto> books
) {}
