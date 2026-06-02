package com.diamond.api.dto;

/**
 * The batter's regressed xwOBA against one of the pitcher's pitch types, with the
 * signed edge vs the league baseline (e.g. "+0.064"). Sorted by pitcher usage.
 */
public record BatterVsArsenalDto(
    String pitchType,
    Double xwobaRegressed,
    Integer pitchesSeen,
    String edge
) {}
