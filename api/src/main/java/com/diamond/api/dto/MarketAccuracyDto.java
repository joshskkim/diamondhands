package com.diamond.api.dto;

import java.util.List;

/**
 * Rolling accuracy for one market: the per-day series (for a trend line) plus the
 * latest day's calibration curve. {@code mae} is set only for the total_runs market.
 */
public record MarketAccuracyDto(
    String market,
    List<AccuracyPointDto> series,
    List<CalibrationBucketDto> calibration,
    Double mae) {}
