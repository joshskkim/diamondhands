package com.diamond.api.dto;

import java.util.List;

/** GET /api/games/{gameId}/odds */
public record GameOddsResponse(
    long gameId,
    boolean hasOdds,
    List<GameMarketDto> game,
    List<PropMarketDto> props
) {}
