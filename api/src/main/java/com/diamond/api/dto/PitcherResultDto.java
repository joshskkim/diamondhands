package com.diamond.api.dto;

/** A starter's actual line for one finished game — used to grade pitcher prop picks. */
public record PitcherResultDto(
    int playerId,
    long gameId,
    Integer strikeouts,
    Integer outs,
    Integer hitsAllowed,
    Integer earnedRuns,
    Integer walks
) {}
