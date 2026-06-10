package com.diamond.api.dto;

/**
 * Compact game-market odds for the today board, taken from a single book
 * (FanDuel — see {@code GameRepository.MAIN_GAME_BOOK}). Any field may be null
 * when the book hasn't posted that market. {@code book} is null only when the
 * game has no odds at all.
 */
public record GameOddsSummaryDto(
    String book,
    Double totalLine,
    Integer totalOverPrice,
    Integer totalUnderPrice,
    Integer homeMoneyline,
    Integer awayMoneyline
) {}
