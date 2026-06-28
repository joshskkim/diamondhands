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
    Integer finalAwayScore,
    // First-inning runs per side, set once the 1st completes (null otherwise) — drives
    // the NRFI/YRFI hit/miss marker on the Sim Signals board.
    Integer finalHomeFirstInningRuns,
    Integer finalAwayFirstInningRuns,
    // Live in-game state (games.live_*), populated by the `live-refresh` ingester while a
    // game is in progress; null for scheduled games. Drives the home board's real-time
    // trackers and is streamed as deltas over /api/games/live/stream. Kept distinct from
    // the Final score above so live data never feeds the grading path.
    Integer liveHomeScore,
    Integer liveAwayScore,
    Integer liveCurrentInning,
    String liveInningState,
    Boolean liveIsTop
) {}
