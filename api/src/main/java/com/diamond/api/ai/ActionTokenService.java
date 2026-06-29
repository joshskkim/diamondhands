package com.diamond.api.ai;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;

import javax.crypto.Mac;
import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

/**
 * Signs/verifies the short-lived token that gates a confirmed write action. The proposal the user
 * sees is bound into an HMAC-signed token (over action + payload + userId + expiry, using the same
 * server secret as the session JWT). {@code /api/agent/confirm} replays the EXACT payload from the
 * token — so a confirmed write executes precisely what was approved, with no second model call and
 * no way for a client to forge a different action.
 */
@Service
public class ActionTokenService {

    private static final long TTL_SECONDS = 600; // 10 minutes to confirm
    private static final String HMAC_ALGO = "HmacSHA256";

    private final SecretKey key; // reuses the JWT signing key bean from SecurityConfig
    private final ObjectMapper mapper;

    public ActionTokenService(SecretKey jwtSecretKey, ObjectMapper mapper) {
        this.key = jwtSecretKey;
        this.mapper = mapper;
    }

    public record VerifiedAction(String action, Map<String, Object> payload, long userId) {}

    /** token = base64url(claimsJson) + "." + base64url(hmac(claimsJson)). */
    public String sign(AgentProposal proposal, long userId) {
        try {
            Map<String, Object> claims = new LinkedHashMap<>();
            claims.put("action", proposal.action());
            claims.put("payload", proposal.payload());
            claims.put("userId", userId);
            claims.put("exp", Instant.now().getEpochSecond() + TTL_SECONDS);
            byte[] json = mapper.writeValueAsBytes(claims);
            String body = base64(json);
            return body + "." + base64(hmac(json));
        } catch (Exception e) {
            throw new IllegalStateException("failed to sign action token", e);
        }
    }

    /** Verify signature + expiry + that the token belongs to this user. */
    @SuppressWarnings("unchecked")
    public Optional<VerifiedAction> verify(String token, long userId) {
        if (token == null) {
            return Optional.empty();
        }
        int dot = token.indexOf('.');
        if (dot <= 0) {
            return Optional.empty();
        }
        try {
            byte[] json = Base64.getUrlDecoder().decode(token.substring(0, dot));
            byte[] sig = Base64.getUrlDecoder().decode(token.substring(dot + 1));
            if (!constantTimeEquals(sig, hmac(json))) {
                return Optional.empty();
            }
            Map<String, Object> claims = mapper.readValue(json, Map.class);
            long exp = ((Number) claims.get("exp")).longValue();
            if (Instant.now().getEpochSecond() > exp) {
                return Optional.empty();
            }
            if (((Number) claims.get("userId")).longValue() != userId) {
                return Optional.empty();
            }
            return Optional.of(new VerifiedAction(
                (String) claims.get("action"),
                (Map<String, Object>) claims.get("payload"),
                userId));
        } catch (Exception e) {
            return Optional.empty();
        }
    }

    private byte[] hmac(byte[] data) throws Exception {
        Mac mac = Mac.getInstance(HMAC_ALGO);
        mac.init(key);
        return mac.doFinal(data);
    }

    private static String base64(byte[] b) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(b);
    }

    private static boolean constantTimeEquals(byte[] a, byte[] b) {
        if (a.length != b.length) {
            return false;
        }
        int r = 0;
        for (int i = 0; i < a.length; i++) {
            r |= a[i] ^ b[i];
        }
        return r == 0;
    }
}
