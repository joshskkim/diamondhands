package com.diamond.api.dto;

/** One decile of a calibration curve: predicted-probability bin vs realized rate. */
public record CalibrationBucketDto(
    double lo,
    double hi,
    int n,
    double predictedMean,
    double actualRate) {}
