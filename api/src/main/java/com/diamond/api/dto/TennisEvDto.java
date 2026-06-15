package com.diamond.api.dto;

/** The model's best match-winner play: the side whose model probability exceeds
 *  its de-vigged fair probability, with the best available price. */
public record TennisEvDto(
    String side,            // "player_a" | "player_b"
    String playerName,
    String bookmaker,
    Integer priceAmerican,
    Double priceDecimal,
    Double modelProb,
    Double fairProb,
    Double edgePct,         // (modelProb - fairProb) * 100
    Double evPct            // expected value per unit staked, percent
) {}
