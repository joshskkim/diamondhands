package com.diamond.api.dto;

public record TennisMatchDto(
    long matchId,
    String startTimeUtc,
    String surface,
    Integer bestOf,
    TennisPlayerDto playerA,
    TennisPlayerDto playerB,
    Double pWinA,            // model P(player A wins)
    Double expTotalGames,
    TennisEvDto bestPlay,    // null when no odds / no projection
    String status
) {}
