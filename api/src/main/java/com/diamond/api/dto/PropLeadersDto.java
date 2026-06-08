package com.diamond.api.dto;

import java.util.List;

/**
 * Slate-wide prop leaderboards: the most likely batters for each market.
 * hits = P(>=1 hit), homeRuns = P(>=1 HR), strikeouts = P(>=1 K),
 * totalBases = expected total bases.
 */
public record PropLeadersDto(
    List<PropLeaderDto> hits,
    List<PropLeaderDto> homeRuns,
    List<PropLeaderDto> totalBases,
    List<PropLeaderDto> strikeouts
) {}
