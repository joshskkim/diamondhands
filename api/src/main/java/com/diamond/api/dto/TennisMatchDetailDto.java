package com.diamond.api.dto;

import java.util.List;

public record TennisMatchDetailDto(
    long matchId,
    String startTimeUtc,
    String surface,
    Integer bestOf,
    String status,
    TennisPlayerDto playerA,
    TennisPlayerDto playerB,
    Double eloA,             // surface-blended Elo used in the projection
    Double eloB,
    Double pWinA,
    Double pServeA,
    Double pServeB,
    Double expTotalGames,
    Double probStraightSets,
    List<TennisQuoteDto> quotes,
    TennisEvDto bestPlay,
    TennisTotalEvDto bestTotalPlay
) {}
