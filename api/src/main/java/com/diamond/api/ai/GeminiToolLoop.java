package com.diamond.api.ai;

import com.google.genai.Client;
import com.google.genai.types.Content;
import com.google.genai.types.FunctionCall;
import com.google.genai.types.FunctionDeclaration;
import com.google.genai.types.GenerateContentConfig;
import com.google.genai.types.GenerateContentResponse;
import com.google.genai.types.Part;
import com.google.genai.types.Tool;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * A reusable, bounded Gemini function-calling loop — the proven body of {@link AskService}
 * generalized so any role (co-pilot, bull, skeptic) can run it over its own tool menu while
 * every tool call is recorded to the trajectory log ({@code agent_steps}). The model calls
 * tools, we execute them, feed the JSON back, and stop when it answers in plain text or hits
 * the iteration cap. Pure orchestration: persistence is the caller's {@link Steps} sink.
 */
@Component
public class GeminiToolLoop {

    /** Live "agent working" status feed (one per tool call). */
    public interface Status {
        void status(String toolName, String label);
    }

    /** Trajectory recorder: one call per executed tool. */
    public interface Steps {
        void step(String role, String toolName, Map<String, Object> args, String resultSummary, long latencyMs);
    }

    /** Executes a tool name -> JSON result fed back to the model. Lets the caller intercept writes. */
    public interface Executor {
        String execute(String toolName, Map<String, Object> args);
    }

    /** Maps a tool name to a human label (status feed). */
    public interface Labeler {
        String label(String toolName);
    }

    /** Optional in-app deep link for a tool call. */
    public interface LinkResolver {
        Optional<LinkRef> linkFor(String toolName, Map<String, Object> args, String resultJson);
    }

    public record Result(String text, List<String> toolsUsed, List<LinkRef> links, int toolCalls, boolean hitLimit) {}

    /**
     * Run the loop for one role. {@code systemPrompt} is the role instruction; {@code decls} is its
     * menu; {@code exec} runs the tools; {@code role} tags the trajectory rows.
     */
    public Result run(Client client, String model, String role, String systemPrompt,
                      List<FunctionDeclaration> decls, Executor exec, Labeler labeler, LinkResolver links,
                      String userText, int maxIters, long maxTokens, Status status, Steps steps) {

        GenerateContentConfig config = GenerateContentConfig.builder()
            .systemInstruction(Content.fromParts(Part.fromText(systemPrompt)))
            .tools(Tool.builder().functionDeclarations(decls.toArray(new FunctionDeclaration[0])).build())
            .maxOutputTokens((int) maxTokens)
            .build();

        List<Content> contents = new ArrayList<>();
        contents.add(Content.builder().role("user").parts(Part.fromText(userText)).build());

        List<String> used = new ArrayList<>();
        Map<String, LinkRef> linkMap = new LinkedHashMap<>();
        int toolCalls = 0;

        for (int iteration = 0; iteration < maxIters; iteration++) {
            GenerateContentResponse response = client.models.generateContent(model, contents, config);

            List<FunctionCall> calls = response.functionCalls();
            if (calls == null || calls.isEmpty()) {
                String answer = response.text();
                return new Result(answer == null ? "" : answer.trim(), used,
                    new ArrayList<>(linkMap.values()), toolCalls, false);
            }

            response.candidates()
                .flatMap(list -> list.isEmpty() ? Optional.empty() : list.get(0).content())
                .ifPresent(contents::add);

            List<Part> resultParts = new ArrayList<>();
            for (FunctionCall call : calls) {
                String name = call.name().orElse("");
                if (status != null) {
                    status.status(name, labeler.label(name));
                }
                used.add(name);
                toolCalls++;
                Map<String, Object> args = call.args().orElse(Map.of());
                long t0 = System.currentTimeMillis();
                String result = exec.execute(name, args);
                long ms = System.currentTimeMillis() - t0;
                if (links != null) {
                    links.linkFor(name, args, result).ifPresent(l -> linkMap.putIfAbsent(l.href(), l));
                }
                if (steps != null) {
                    steps.step(role, name, args, summarize(result), ms);
                }
                resultParts.add(Part.fromFunctionResponse(name, Map.of("result", result)));
            }
            contents.add(Content.builder().role("user").parts(resultParts).build());
        }

        return new Result("", used, new ArrayList<>(linkMap.values()), toolCalls, true);
    }

    /** Keep the full tool JSON in the trajectory but cap it so a huge board doesn't bloat the log. */
    private static String summarize(String result) {
        if (result == null) {
            return null;
        }
        return result.length() <= 8000 ? result : result.substring(0, 8000) + "…";
    }
}
