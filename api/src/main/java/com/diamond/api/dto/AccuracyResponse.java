package com.diamond.api.dto;

import java.util.List;

/** GET /api/accuracy?days=N — rolling projection accuracy for the current model version. */
public record AccuracyResponse(
    int days,
    String modelVersion,
    List<MarketAccuracyDto> markets) {}
