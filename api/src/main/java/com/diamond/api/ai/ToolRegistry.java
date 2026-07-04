package com.diamond.api.ai;

import com.google.genai.types.FunctionDeclaration;

import java.util.Map;
import java.util.Optional;

/**
 * A named set of read tools the agent can call. {@link AskToolRegistry} (general read surface)
 * and {@link SkepticToolRegistry} (contrarian signals) both implement this so the same bounded
 * tool-use loop ({@link GeminiToolLoop}) can drive any role — the plain co-pilot, the bull, or
 * the skeptic — over a different menu without duplicating loop logic.
 */
public interface ToolRegistry {

    /** The tool menu offered to the model. */
    java.util.List<FunctionDeclaration> declarations();

    /** Execute a tool by name against the live services; always returns JSON (errors included). */
    String execute(String name, Map<String, Object> args);

    /** Short human label for the live "agent working" status feed. */
    String label(String name);

    /** Optional in-app deep link for a tool call (empty when the tool has no natural page). */
    default Optional<LinkRef> linkFor(String name, Map<String, Object> args, String resultJson) {
        return Optional.empty();
    }
}
