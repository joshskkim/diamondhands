package com.diamond.api.controller;

import com.google.genai.Client;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.web.server.ResponseStatusException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.catchThrowableOfType;

/**
 * The debate gate is server-to-server: it must reject anything without the internal key (403) and
 * degrade to 503 when AI is off (so record-picks falls back to a mechanical board).
 */
class DebateControllerTest {

    private static ObjectProvider<Client> provider(Client c) {
        return new ObjectProvider<>() {
            @Override public Client getObject(Object... args) { return c; }
            @Override public Client getObject() { return c; }
            @Override public Client getIfAvailable() { return c; }
            @Override public Client getIfUnique() { return c; }
        };
    }

    private static DebateController.DebateRequest req() {
        return new DebateController.DebateRequest(1, "hr", "over", 0.5, 10, "A B", -110, 0.6, 0.5);
    }

    private static int status(DebateController ctrl, String key) {
        ResponseStatusException ex = catchThrowableOfType(
            () -> ctrl.debatePick(key, req()), ResponseStatusException.class);
        return ex.getStatusCode().value();
    }

    @Test
    void rejectsWrongOrMissingKey() {
        DebateController ctrl = new DebateController(null, provider(null), "secret");
        assertThat(status(ctrl, "wrong")).isEqualTo(403);
        assertThat(status(ctrl, null)).isEqualTo(403);
    }

    @Test
    void rejectsWhenKeyNotConfigured() {
        DebateController ctrl = new DebateController(null, provider(null), "");
        assertThat(status(ctrl, "anything")).isEqualTo(403);
    }

    @Test
    void serviceUnavailableWhenAiOff() {
        // valid key, but no Gemini client wired → 503 (record-picks treats this as "no gate")
        DebateController ctrl = new DebateController(null, provider(null), "secret");
        assertThat(status(ctrl, "secret")).isEqualTo(503);
    }
}
