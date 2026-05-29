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
    String status
) {}
