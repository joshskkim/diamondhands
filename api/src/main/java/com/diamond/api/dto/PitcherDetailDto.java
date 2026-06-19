package com.diamond.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * One starting pitcher's full breakdown for the game view's Pitchers tab: identity plus
 * the pitch-mix arsenal (usage / velo / whiff / xwOBA-against per pitch type, vs both
 * batter hands) and the season skill splits vs LHB / RHB. Arsenal and skill are empty
 * lists (never null) when no snapshot rows exist yet — the UI degrades gracefully.
 */
public record PitcherDetailDto(
    int id,
    String name,
    @JsonProperty("throws") String throws_,
    String teamAbbr,
    List<PitchArsenalDto> arsenal,
    List<PitcherSkillSplitDto> skill
) {}
