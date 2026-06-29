package com.diamond.api.ai;

import java.util.List;

/**
 * An {@link AgentSink} that discards everything — used to drive a {@link DebateOrchestrator}
 * debate synchronously (server-to-server, no SSE/UI) for the promotion gate. The verdict is the
 * return value; the streamed turns aren't needed here.
 */
public final class NoOpSink implements AgentSink {

    public static final NoOpSink INSTANCE = new NoOpSink();

    private NoOpSink() {}

    @Override public void thread(long threadId) {}
    @Override public void status(String toolName, String label) {}
    @Override public void role(String role, String text) {}
    @Override public void links(List<LinkRef> links) {}
    @Override public void confirm(String token, AgentProposal proposal) {}
    @Override public void answer(String text) {}
    @Override public void sources(List<String> toolNames) {}
    @Override public void error(String message) {}
}
