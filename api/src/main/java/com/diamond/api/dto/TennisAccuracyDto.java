package com.diamond.api.dto;

import java.util.List;

/** Out-of-sample match-winner accuracy for one surface: a monthly Brier/ECE series
 *  plus a merged calibration scatter. */
public record TennisAccuracyDto(
    String modelVersion,
    String surface,
    List<Point> series,
    List<CalibrationBucket> calibration
) {
    public record Point(String period, int n, Double brier, Double baselineBrier, Double ece) {}

    public record CalibrationBucket(double lo, double hi, int n, double predictedMean, double actualRate) {}
}
