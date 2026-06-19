package com.diamond.api.dto;

/**
 * A starting pitcher's season skill split against one batter handedness, read from
 * {@code pitcher_skill}. Any rate may be null when the sample is too thin to populate.
 */
public record PitcherSkillSplitDto(
    String vsHand,        // 'L' | 'R'
    Double kRate,
    Double bbRate,
    Double xwobaAgainst,
    Double hrPerPa,
    Integer battersFaced
) {}
