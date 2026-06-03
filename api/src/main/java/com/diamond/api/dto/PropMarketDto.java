package com.diamond.api.dto;

/** A player prop (hit | hr | pitcher_k | pitcher_outs) at one line, over/under quotes. */
public record PropMarketDto(
    PlayerDto player,
    String market,
    Double line,
    LineQuoteDto over,
    LineQuoteDto under
) {}
