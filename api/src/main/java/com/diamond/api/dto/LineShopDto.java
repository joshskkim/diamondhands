package com.diamond.api.dto;

import java.util.List;

/**
 * Per-selection book ladder for line shopping. {@code key} is
 * "gameId:playerId:market:side:line" (line trailing-zero-stripped) so the client can
 * join it to a Best Lines row built from the same fields. {@code quotes} is sorted
 * best-price-first (highest decimal odds for the bettor).
 */
public record LineShopDto(
    String key,
    List<BookQuoteDto> quotes
) {}
