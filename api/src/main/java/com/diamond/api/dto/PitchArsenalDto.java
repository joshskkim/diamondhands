package com.diamond.api.dto;

/** One pitch type in an opposing pitcher's arsenal vs the batter's hand. */
public record PitchArsenalDto(
    String pitchType,
    Double usageRate,
    Double leagueXwoba
) {}
