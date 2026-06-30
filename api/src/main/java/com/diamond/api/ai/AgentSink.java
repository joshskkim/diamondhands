package com.diamond.api.ai;

import java.util.List;

/**
 * Streaming callbacks for the stateful agent, pushed to the client over SSE. Extends the
 * "Ask Diamond" feed with two agentic additions: {@link #role} (a bull/skeptic/judge debate turn)
 * and {@link #confirm} (a proposed write action the user must approve before it executes).
 */
public interface AgentSink {

    /** The conversation thread this turn belongs to (sent first so the client threads the next turn). */
    void thread(long threadId);

    /** One per tool the agent calls (live "working" feed). */
    void status(String toolName, String label);

    /** A debate role's contribution (role = bull | skeptic | judge). */
    void role(String role, String text);

    /** In-app deep links derived from the tools used. */
    void links(List<LinkRef> links);

    /** A write the user must confirm: the signed token + the human-readable proposal. */
    void confirm(String token, AgentProposal proposal);

    /** The final natural-language answer. */
    void answer(String text);

    /** The tools used (provenance). */
    void sources(List<String> toolNames);

    void error(String message);
}
