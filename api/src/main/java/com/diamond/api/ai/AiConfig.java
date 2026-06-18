package com.diamond.api.ai;

import com.google.genai.Client;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Wires the Gemini (Google Gen AI) client for the "Ask Diamond" feature. The bean only exists
 * when {@code app.ai.enabled=true}; everywhere else (default) the feature stays dark and
 * {@code /api/ask} returns 503 — so a missing key never breaks the rest of the API.
 */
@Configuration
public class AiConfig {

    @Bean
    @ConditionalOnProperty(name = "app.ai.enabled", havingValue = "true")
    public Client genaiClient(@Value("${app.ai.api-key:}") String apiKey) {
        return Client.builder().apiKey(apiKey).build();
    }
}
