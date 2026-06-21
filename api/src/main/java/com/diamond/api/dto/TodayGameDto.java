package com.diamond.api.dto;

public record TodayGameDto(
    long gameId,
    String startTimeUtc,
    TeamDto home,
    TeamDto away,
    StadiumDto stadium,
    WeatherDto weather,
    ProbablesDto probables,
    ProjectionSummaryDto projection,
    GameOddsSummaryDto odds,
    String status,
    // Final score once the game is over (null while scheduled / in progress) — drives
    // the projected-winner hit/miss marker on the slate.
    Integer finalHomeScore,
    Integer finalAwayScore
) {}
