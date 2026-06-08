package com.diamond.api.auth;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.lang.NonNull;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtException;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.List;

/**
 * Reads the session JWT from the {@code diamond_session} cookie and, if valid, sets the
 * authentication. An absent/invalid/expired cookie simply proceeds unauthenticated — so a stale
 * cookie never breaks public GET endpoints; authorization rules decide what needs a login.
 */
public class JwtCookieAuthFilter extends OncePerRequestFilter {

    public static final String COOKIE = "diamond_session";

    private final JwtDecoder decoder;

    public JwtCookieAuthFilter(JwtDecoder decoder) {
        this.decoder = decoder;
    }

    @Override
    protected void doFilterInternal(@NonNull HttpServletRequest request,
                                    @NonNull HttpServletResponse response,
                                    @NonNull FilterChain chain) throws ServletException, IOException {
        String token = readCookie(request);
        if (token != null && SecurityContextHolder.getContext().getAuthentication() == null) {
            try {
                Jwt jwt = decoder.decode(token);
                AuthUser user = new AuthUser(
                    Long.parseLong(jwt.getSubject()),
                    jwt.getClaimAsString("email"),
                    jwt.getClaimAsString("handle"));
                var auth = new UsernamePasswordAuthenticationToken(user, null, List.of());
                SecurityContextHolder.getContext().setAuthentication(auth);
            } catch (JwtException | NumberFormatException ignored) {
                // invalid/expired cookie → stay unauthenticated
            }
        }
        chain.doFilter(request, response);
    }

    private static String readCookie(HttpServletRequest request) {
        Cookie[] cookies = request.getCookies();
        if (cookies == null) return null;
        for (Cookie c : cookies) {
            if (COOKIE.equals(c.getName())) return c.getValue();
        }
        return null;
    }
}
