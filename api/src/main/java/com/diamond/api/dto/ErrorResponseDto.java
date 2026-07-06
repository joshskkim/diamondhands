package com.diamond.api.dto;

import java.time.Instant;

/**
 * Uniform error body for every non-2xx JSON response (see ApiExceptionHandler). Clients key
 * off {@code status}; {@code message} is human-readable and safe to display (5xx bodies never
 * leak internals — the handler substitutes a generic message and logs the real cause).
 */
public record ErrorResponseDto(
    int status,
    String error,
    String message,
    String path,
    Instant timestamp
) {}
