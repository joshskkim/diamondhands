package com.diamond.api.dto;

/**
 * Full-game total: the sim's expected total and P(over) vs the consensus book line.
 * {@code edge} is simTotal - bookLine (positive = sim leans over); {@code lean} is the
 * side the sim favors. bookLine/edge/pOver are null when no book total is stored.
 */
public record GameTotalDto(
    long gameId,
    String matchup,
    double simTotal,
    Double bookLine,
    Double edge,
    Double pOver,
    String lean
) {}
