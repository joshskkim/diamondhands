package com.diamond.api.config;

import com.diamond.api.dto.ErrorResponseDto;
import jakarta.servlet.http.HttpServletRequest;
import java.time.Instant;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler;

/**
 * Global error shape for the whole API: every non-2xx JSON response is an
 * {@link ErrorResponseDto}, so controllers just throw {@link ResponseStatusException} with a
 * reason and never hand-build error bodies.
 *
 * <p>Extends {@link ResponseEntityExceptionHandler} so Spring MVC's own exceptions (bad
 * request params, unsupported media types, ...) keep their standard status codes instead of
 * being swallowed by the 500 catch-all. Exceptions thrown after an SSE stream has started
 * (ask/agent/debate) are outside this handler's reach by nature.
 */
@RestControllerAdvice
public class ApiExceptionHandler extends ResponseEntityExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(ApiExceptionHandler.class);

    @ExceptionHandler(ResponseStatusException.class)
    public ResponseEntity<ErrorResponseDto> handleResponseStatus(
            ResponseStatusException ex, HttpServletRequest request) {
        HttpStatusCode status = ex.getStatusCode();
        String error = status instanceof HttpStatus hs ? hs.getReasonPhrase() : status.toString();
        String message = ex.getReason() != null ? ex.getReason() : error;
        return ResponseEntity.status(status)
            .body(new ErrorResponseDto(status.value(), error, message, request.getRequestURI(), Instant.now()));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ErrorResponseDto> handleUnexpected(Exception ex, HttpServletRequest request) {
        log.error("Unhandled exception on {} {}", request.getMethod(), request.getRequestURI(), ex);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
            .body(new ErrorResponseDto(
                HttpStatus.INTERNAL_SERVER_ERROR.value(),
                HttpStatus.INTERNAL_SERVER_ERROR.getReasonPhrase(),
                "Something went wrong handling this request.",
                request.getRequestURI(), Instant.now()));
    }
}
