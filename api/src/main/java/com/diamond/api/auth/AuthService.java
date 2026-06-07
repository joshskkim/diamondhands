package com.diamond.api.auth;

import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

/** Sign-up / sign-in: validates credentials and returns the resolved {@link AuthUser}. */
@Service
public class AuthService {

    private final UserRepository users;
    private final PasswordEncoder passwordEncoder;

    public AuthService(UserRepository users, PasswordEncoder passwordEncoder) {
        this.users = users;
        this.passwordEncoder = passwordEncoder;
    }

    public AuthUser signup(String email, String handle, String rawPassword) {
        String normalized = email.trim().toLowerCase();
        if (users.findByEmail(normalized).isPresent()) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Email already registered");
        }
        if (users.findByHandle(handle).isPresent()) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Handle already taken");
        }
        long id = users.insert(normalized, handle, passwordEncoder.encode(rawPassword));
        return new AuthUser(id, normalized, handle);
    }

    public AuthUser signin(String email, String rawPassword) {
        String normalized = email.trim().toLowerCase();
        // Same generic error for unknown email vs. bad password — don't leak which.
        UserRepository.UserRow row = users.findByEmail(normalized)
            .orElseThrow(() -> new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid email or password"));
        if (!passwordEncoder.matches(rawPassword, row.passwordHash())) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid email or password");
        }
        return new AuthUser(row.id(), row.email(), row.handle());
    }
}
