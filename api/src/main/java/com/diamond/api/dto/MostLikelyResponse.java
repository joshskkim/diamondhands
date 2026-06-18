package com.diamond.api.dto;

import java.util.List;

/**
 * The "Most Likely" board: the game simulator's headline picks for a slate —
 * full-game totals vs the book line, run-line (spread) leans, NRFI/YRFI, and the top
 * player props. {@code date} is an ISO date string (the cached Redis JSON serializer has
 * no JSR-310 module).
 */
public record MostLikelyResponse(
    String date,
    List<GameTotalDto> totals,
    List<NrfiDto> nrfi,
    List<RunLineDto> runLine,
    PropLeadersDto props
) {}
