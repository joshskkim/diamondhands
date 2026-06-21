package com.diamond.api.metrics;

import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;

/** Enables {@code @Scheduled} so {@link BusinessMetrics} can refresh its gauges periodically. */
@Configuration
@EnableScheduling
public class MetricsConfig {}
