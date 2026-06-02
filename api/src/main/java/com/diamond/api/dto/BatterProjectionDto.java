package com.diamond.api.dto;

import java.util.List;

public record BatterProjectionDto(
    PlayerDto player,
    PitcherDto opposingPitcher,
    Double expectedPa,
    ProbabilitiesDto probabilities,
    Double expectedHits,
    Double expectedTotalBases,
    AdjustmentsDto adjustments,
    String pitcherDataQuality,
    Integer lineupPosition,
    Boolean lineupConfirmed,
    Double matchupXwoba,
    String matchupQuality,
    List<PitchArsenalDto> pitcherArsenal,
    List<BatterVsArsenalDto> batterVsArsenal
) {}
