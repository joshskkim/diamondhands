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
    // MLB detailedState (Postponed / Suspended / Cancelled / Delayed …) when it differs
    // from the coarse abstractGameState in `status`. Null for a normal game. Lets the slate
    // card badge a dead game — whose projections/picks are pulled off the boards.
    String detailedStatus,
    // Final score once the game is over (null while scheduled / in progress) — drives
    // the projected-winner hit/miss marker on the slate.
    Integer finalHomeScore,
    Integer finalAwayScore
) {}
