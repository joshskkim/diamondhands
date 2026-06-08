package com.diamond.api.dto;

/**
 * First-five-innings (F5) markets — the sim's most rigorous period (starter-driven).
 * F5 total + P(over) vs the consensus book F5 line, and the F5 moneyline favorite
 * (team abbr more likely to lead after five) with its probability and the push rate.
 */
public record F5Dto(
    long gameId,
    String matchup,
    double f5Total,
    Double bookLine,
    Double edge,
    Double pOver,
    String favorite,
    double favoriteProb,
    double pTie
) {}
