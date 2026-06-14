package com.diamond.api.config;

import io.micrometer.observation.ObservationRegistry;
import io.micrometer.observation.aop.ObservedAspect;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Wires Micrometer's {@link ObservedAspect} so {@code @Observed}-annotated service methods
 * emit a timed metric (latency percentiles) and a child span in the OpenTelemetry trace.
 * Combined with per-JDBC-query spans from datasource-micrometer, this is what makes a
 * request's DB fan-out (e.g. the prop-board N+1) visible as a trace waterfall.
 */
@Configuration
public class ObservabilityConfig {

    @Bean
    ObservedAspect observedAspect(ObservationRegistry registry) {
        return new ObservedAspect(registry);
    }
}
