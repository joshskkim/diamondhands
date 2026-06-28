package com.diamond.api.dto;

/** A batter's actual line for one finished game — used to grade prop-board picks. */
public record BatterResultDto(
    int playerId,
    long gameId,
    Integer atBats,
    Integer hits,
    Integer homeRuns,
    Integer strikeouts,
    Integer walks
) {}
