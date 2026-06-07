package com.diamond.api.auth;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/** Email+password auth. Sign-up/sign-in set the session cookie; /me returns the current user. */
@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final AuthService auth;
    private final JwtService jwt;
    private final AuthProperties props;

    public AuthController(AuthService auth, JwtService jwt, AuthProperties props) {
        this.auth = auth;
        this.jwt = jwt;
        this.props = props;
    }

    public record SignupRequest(
        @Email @NotBlank String email,
        @Pattern(regexp = "[A-Za-z0-9_]{3,20}",
            message = "Handle must be 3–20 letters, numbers, or underscores") String handle,
        @Size(min = 8, max = 100, message = "Password must be 8–100 characters") String password) {}

    public record SigninRequest(@Email @NotBlank String email, @NotBlank String password) {}

    public record UserResponse(long id, String email, String handle) {
        static UserResponse of(AuthUser u) {
            return new UserResponse(u.id(), u.email(), u.handle());
        }
    }

    @PostMapping("/signup")
    public ResponseEntity<UserResponse> signup(@Valid @RequestBody SignupRequest req) {
        return withSession(auth.signup(req.email(), req.handle(), req.password()));
    }

    @PostMapping("/signin")
    public ResponseEntity<UserResponse> signin(@Valid @RequestBody SigninRequest req) {
        return withSession(auth.signin(req.email(), req.password()));
    }

    @PostMapping("/signout")
    public ResponseEntity<Void> signout() {
        String cleared = baseCookie("").maxAge(0).build().toString();
        return ResponseEntity.noContent().header(HttpHeaders.SET_COOKIE, cleared).build();
    }

    @GetMapping("/me")
    public UserResponse me(@AuthenticationPrincipal AuthUser user) {
        if (user == null) throw new ResponseStatusException(HttpStatus.UNAUTHORIZED);
        return UserResponse.of(user);
    }

    private ResponseEntity<UserResponse> withSession(AuthUser user) {
        String cookie = baseCookie(jwt.issue(user)).maxAge(props.sessionTtl()).build().toString();
        return ResponseEntity.ok().header(HttpHeaders.SET_COOKIE, cookie).body(UserResponse.of(user));
    }

    private ResponseCookie.ResponseCookieBuilder baseCookie(String value) {
        return ResponseCookie.from(JwtCookieAuthFilter.COOKIE, value)
            .httpOnly(true)
            .sameSite("Lax")
            .path("/")
            .secure(props.cookieSecure());
    }
}
