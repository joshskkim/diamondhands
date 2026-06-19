package com.diamond.api.dto;

public record GameProjectionsResponse(
    long gameId, TeamBattersDto home, TeamBattersDto away, GamePitchersDto pitchers) {}
