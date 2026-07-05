package com.diamond.api.dto;

/**
 * Full-game run-line (spread) lean from the game simulator's joint run distribution.
 * Unlike the old favorite-only framing, this names whichever side carries the better
 * de-vigged edge: {@code team} is that side's abbr, {@code side} is "home"/"away", and
 * {@code line} is what that team lays or takes (-1.5 for a favorite, +1.5 for an
 * underdog). {@code coverProb} is the sim's probability of that exact side covering;
 * {@code edge} = coverProb minus the no-vig book implied for the same side (null when
 * the slate has no run-line odds — then this falls back to the sim favorite laying -1.5).
 */
public record RunLineDto(
    long gameId,
    String matchup,
    String team,
    String side,
    double line,
    double coverProb,
    Double bookLine,
    Double edge
) {}
