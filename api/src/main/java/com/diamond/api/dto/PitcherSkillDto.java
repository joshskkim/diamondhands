package com.diamond.api.dto;

/** A pitcher's season skill line vs one batter handedness ('L'/'R'). */
public record PitcherSkillDto(
    String vsHand,
    Double kRate,
    Double bbRate,
    Double xwobaAgainst,
    Double hrPerPa,
    Integer battersFaced
) {}
