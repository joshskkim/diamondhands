package com.diamond.api.dto;

/**
 * Full-game run-line (spread) lean from the game simulator's joint run distribution.
 * {@code favorite} is the team abbr laying the -1.5; {@code coverProb} is that side's
 * simulated probability of covering. {@code edge} = coverProb minus the no-vig book
 * implied for the same side (null when the slate has no run-line odds).
 */
public record RunLineDto(
    long gameId,
    String matchup,
    String favorite,
    double coverProb,
    Double bookLine,
    Double edge
) {}
