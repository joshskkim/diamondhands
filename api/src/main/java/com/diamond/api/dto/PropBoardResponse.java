package com.diamond.api.dto;

import java.util.List;

/**
 * Model-first prop board for a slate: one pick per market, ranked purely by model
 * probability (a likelihood board, not a value board). {@code battersConsidered} is
 * the number of projected batters surveyed, so the client can be honest when the
 * board is empty. {@code pitcherPicks} are the starting-pitcher analogues (strikeouts,
 * outs), ranked by expected volume rather than by P(clear) — see PitcherPropPickDto.
 */
public record PropBoardResponse(
    String date,
    int battersConsidered,
    List<PropBoardPickDto> picks,
    List<PitcherPropPickDto> pitcherPicks
) {}
