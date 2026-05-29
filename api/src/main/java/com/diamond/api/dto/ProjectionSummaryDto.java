package com.diamond.api.dto;

public record ProjectionSummaryDto(
    Double expectedHomeRuns,
    Double expectedAwayRuns,
    Double expectedTotal,
    String projectedAt
) {}
