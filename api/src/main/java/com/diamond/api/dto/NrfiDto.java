package com.diamond.api.dto;

/**
 * First-inning run market for a game: simulated P(yes run, 1st inning) and its
 * complement (NRFI), plus the side the sim leans and its probability.
 */
public record NrfiDto(
    long gameId,
    String matchup,
    double pYrfi,
    double pNrfi,
    String lean,        // "NRFI" or "YRFI"
    double leanProb
) {}
