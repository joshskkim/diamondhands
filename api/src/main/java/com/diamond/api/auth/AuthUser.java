package com.diamond.api.auth;

/**
 * The authenticated principal carried in the SecurityContext and exposed to controllers.
 * Identity is keyed by the stable internal {@code users.id} — everything user-owned references
 * this, keeping the credential layer swappable (see docs/auth-design.md).
 */
public record AuthUser(long id, String email, String handle) {}
