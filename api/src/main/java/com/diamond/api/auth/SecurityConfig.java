package com.diamond.api.auth;

import com.nimbusds.jose.jwk.source.ImmutableSecret;
import com.nimbusds.jose.jwk.source.JWKSource;
import com.nimbusds.jose.proc.SecurityContext;
import jakarta.servlet.DispatcherType;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtEncoder;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.security.oauth2.jwt.NimbusJwtEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.web.cors.CorsConfigurationSource;

import javax.crypto.SecretKey;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;

/**
 * Stateless cookie-JWT security. Existing GET data endpoints stay public; only authenticated
 * routes (currently just {@code GET /api/auth/me}, and any future non-GET write endpoint) require
 * a valid session. CSRF is disabled — mitigated by the SameSite cookie + CORS locked to the web app.
 */
@Configuration
@EnableWebSecurity
@EnableConfigurationProperties(AuthProperties.class)
public class SecurityConfig {

    @Bean
    SecretKey jwtSecretKey(AuthProperties props) {
        return new SecretKeySpec(props.jwtSecret().getBytes(StandardCharsets.UTF_8), "HmacSHA256");
    }

    @Bean
    JwtEncoder jwtEncoder(SecretKey key) {
        JWKSource<SecurityContext> jwks = new ImmutableSecret<>(key);
        return new NimbusJwtEncoder(jwks);
    }

    @Bean
    JwtDecoder jwtDecoder(SecretKey key) {
        return NimbusJwtDecoder.withSecretKey(key).macAlgorithm(MacAlgorithm.HS256).build();
    }

    @Bean
    PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    @Bean
    SecurityFilterChain securityFilterChain(HttpSecurity http,
                                            JwtDecoder jwtDecoder,
                                            CorsConfigurationSource corsConfigurationSource) throws Exception {
        http
            .csrf(csrf -> csrf.disable())
            .cors(cors -> cors.configurationSource(corsConfigurationSource))
            .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .authorizeHttpRequests(auth -> auth
                // Let Spring's internal ERROR dispatch through, else thrown 4xx (validation, 409,
                // etc.) re-enter the chain on /error and get masked as 401.
                .dispatcherTypeMatchers(DispatcherType.ERROR).permitAll()
                .requestMatchers(HttpMethod.GET, "/api/auth/me").authenticated()
                .requestMatchers(HttpMethod.POST, "/api/auth/signup", "/api/auth/signin", "/api/auth/signout").permitAll()
                // "Ask Diamond" AI query is a public read-like endpoint (POST only because it
                // takes a question body). Gate to .authenticated() later if it needs sign-in.
                .requestMatchers(HttpMethod.POST, "/api/ask").permitAll()
                // Server-to-server debate gate (record-picks). Not session-auth'd — guarded by
                // the X-Internal-Key header in DebateController. Permit here so the filter chain
                // doesn't 401 it before the controller's key check runs.
                .requestMatchers(HttpMethod.POST, "/api/debate/pick").permitAll()
                // Stripe webhook is public but authenticated by its signature, not the
                // session cookie (it's a server-to-server callback). Checkout/portal POSTs
                // are not GET, so they fall through to .authenticated() below.
                .requestMatchers(HttpMethod.POST, "/api/billing/webhook").permitAll()
                .requestMatchers("/health").permitAll()
                // Health probes + Prometheus scrape are unauthenticated on the local
                // network; other actuator endpoints stay behind auth.
                .requestMatchers("/actuator/health/**", "/actuator/prometheus", "/actuator/info").permitAll()
                .requestMatchers(HttpMethod.GET, "/api/**").permitAll()
                .anyRequest().authenticated())
            .exceptionHandling(e -> e.authenticationEntryPoint(
                (req, res, ex) -> res.setStatus(HttpStatus.UNAUTHORIZED.value())))
            .addFilterBefore(new JwtCookieAuthFilter(jwtDecoder), UsernamePasswordAuthenticationFilter.class);
        return http.build();
    }
}
