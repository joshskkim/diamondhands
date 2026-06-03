package com.diamond.api.dto;

import java.util.List;

/** A game-level market (moneyline | run_line | total) with one quote per side/line. */
public record GameMarketDto(String market, List<LineQuoteDto> quotes) {}
