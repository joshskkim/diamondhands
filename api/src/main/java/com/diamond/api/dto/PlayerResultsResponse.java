package com.diamond.api.dto;

import java.util.List;

/**
 * Actual per-player results for a slate's finished games. Feeds the client's live ✓/✗
 * grading of the Prop Board (batter hit/HR/K/BB, pitcher K/outs/hits/ER) and Model's
 * Picks HR — the game-level grading rides on /api/games/today instead.
 */
public record PlayerResultsResponse(
    String date,
    List<BatterResultDto> batters,
    List<PitcherResultDto> pitchers
) {}
