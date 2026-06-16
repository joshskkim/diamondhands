package com.diamond.api.dto;

/** The model's best total-games (over/under) play at the best-priced line. */
public record TennisTotalEvDto(
    String side,            // "over" | "under"
    Double line,
    String bookmaker,
    Integer priceAmerican,
    Double priceDecimal,
    Double modelProb,
    Double fairProb,
    Double edgePct,
    Double evPct
) {}
