package com.diamond.api.dto;

/** The two probable starters for a game: {@code home} = the home team's starter. */
public record GamePitchersDto(PitcherDetailDto home, PitcherDetailDto away) {}
