package com.diamond.api.ai;

import com.google.genai.Client;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * The graceful-degradation guarantees that keep a missing API key from breaking the app:
 * the feature reports unavailable when disabled or unconfigured, and a call with no client
 * fails soft via the sink rather than throwing.
 */
class AskServiceTest {

    /** Minimal ObjectProvider that always yields {@code value} (house style — no Mockito). */
    static <T> ObjectProvider<T> providerOf(T value) {
        return new ObjectProvider<>() {
            @Override public T getObject() { return value; }
            @Override public T getObject(Object... args) { return value; }
            @Override public T getIfAvailable() { return value; }
            @Override public T getIfUnique() { return value; }
        };
    }

    static final class CapturingSink implements AskService.AskSink {
        String answer;
        String error;
        List<String> sources;
        List<LinkRef> links;
        @Override public void status(String toolName, String label) {}
        @Override public void links(List<LinkRef> links) { this.links = links; }
        @Override public void answer(String text) { this.answer = text; }
        @Override public void sources(List<String> toolNames) { this.sources = toolNames; }
        @Override public void error(String message) { this.error = message; }
    }

    private static AskService service(boolean enabled) {
        return new AskService(providerOf((Client) null), null, enabled,
            "gemini-2.5-flash", 1000L, 3);
    }

    @Test
    void disabledFeatureIsNotAvailable() {
        assertThat(service(false).isAvailable()).isFalse();
    }

    @Test
    void enabledButUnconfiguredIsNotAvailable() {
        assertThat(service(true).isAvailable()).isFalse();
    }

    @Test
    void askWithoutClientFailsSoftViaSink() {
        CapturingSink sink = new CapturingSink();
        service(true).ask("Who's the best bet tonight?", sink);
        assertThat(sink.error).isNotNull();
        assertThat(sink.answer).isNull();
    }
}
