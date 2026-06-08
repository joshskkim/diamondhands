package com.diamond.api.dto;

/**
 * One player's leaderboard entry for a prop market. {@code value} is a probability
 * (hit/HR/K markets) or an expected count (total bases).
 */
public record PropLeaderDto(
    int playerId,
    String player,
    String team,
    String matchup,
    double value
) {}
