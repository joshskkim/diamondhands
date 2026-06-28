package com.diamond.api.dto;

/** Lean live in-game state, streamed as deltas over /api/games/live/stream. */
public record LiveGameDto(
    long gameId,
    String status,
    Integer liveHomeScore,
    Integer liveAwayScore,
    Integer liveCurrentInning,
    String liveInningState,
    Boolean liveIsTop
) {}
