package com.diamond.api.auth;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;

/** Auth/session config (see application.yml `app.auth.*`). */
@ConfigurationProperties(prefix = "app.auth")
public record AuthProperties(String jwtSecret, Duration sessionTtl, boolean cookieSecure) {}
