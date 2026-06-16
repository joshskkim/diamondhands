package com.diamond.api.dto;

/** The model's best ace/DF player-prop play at the best-priced line. */
public record TennisPropEvDto(
    String playerName,
    String market,          // "aces" | "dfs"
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
