package com.diamond.api.ai;

import com.google.genai.Client;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.api.Assertions.assertThat;

/**
 * Request-gating on the SSE endpoint: 503 when the feature is off, 400 on an empty question.
 * (The streaming happy path is exercised end-to-end with a real key — see the plan's
 * verification section.)
 */
class AskControllerTest {

    private static AskService askService(boolean available) {
        return new AskService(AskServiceTest.providerOf((Client) null), null, available,
            "gemini-2.5-flash", 1000L, 3) {
            @Override public boolean isAvailable() { return available; }
            @Override public void ask(String question, AskSink sink) {
                sink.answer("ok");
                sink.sources(List.of());
            }
        };
    }

    private static AskController controller(boolean available) {
        return new AskController(askService(available), new ObjectMapper());
    }

    @Test
    void disabledReturns503() {
        assertThatThrownBy(() -> controller(false).ask(new AskController.AskRequest("hi")))
            .isInstanceOfSatisfying(ResponseStatusException.class,
                e -> assertThat(e.getStatusCode().value()).isEqualTo(503));
    }

    @Test
    void blankQuestionReturns400() {
        assertThatThrownBy(() -> controller(true).ask(new AskController.AskRequest("   ")))
            .isInstanceOfSatisfying(ResponseStatusException.class,
                e -> assertThat(e.getStatusCode().value()).isEqualTo(400));
    }
}
