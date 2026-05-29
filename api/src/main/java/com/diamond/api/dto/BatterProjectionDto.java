package com.diamond.api.dto;

public record BatterProjectionDto(
    PlayerDto player,
    PitcherDto opposingPitcher,
    Double expectedPa,
    ProbabilitiesDto probabilities,
    Double expectedHits,
    Double expectedTotalBases,
    AdjustmentsDto adjustments
) {}
