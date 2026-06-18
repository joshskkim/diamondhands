package com.diamond.api.ai;

import com.google.genai.Client;
import com.google.genai.types.Content;
import com.google.genai.types.FunctionCall;
import com.google.genai.types.FunctionDeclaration;
import com.google.genai.types.GenerateContentConfig;
import com.google.genai.types.GenerateContentResponse;
import com.google.genai.types.Part;
import com.google.genai.types.Tool;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * "Ask Diamond" orchestrator. Runs a server-side Gemini function-calling loop: the model calls the
 * read tools in {@link AskToolRegistry} against the live services, and we feed the JSON back
 * until it produces a grounded answer. Progress (each tool call) and the final answer are
 * pushed to an {@link AskSink} so the controller can stream them over SSE.
 */
@Service
public class AskService {

    /** Callbacks for streaming progress to the client. Implemented by the SSE controller. */
    public interface AskSink {
        void status(String toolName, String label);
        void links(List<LinkRef> links);
        void answer(String text);
        void sources(List<String> toolNames);
        void error(String message);
    }

    private static final String SYSTEM_PROMPT = """
        You are Diamond's analyst — a baseball and tennis betting assistant for a stats-first
        projection app. Answer the user's question using ONLY the provided tools, which read the
        app's real projections, sportsbook odds/EV, and model-accuracy data. Today is %s.

        Rules:
        - Ground every claim in tool results. Never invent players, games, numbers, or lines.
          If the tools don't cover something, say so plainly.
        - Resolve player names with search_player before calling get_player.
        - Cite the actual figures (probabilities, EV%%, edges, prices) you used.
        - Be concise and lead with the answer. Probabilities are 0-1 unless shown as a price.
        - This is informational analysis of a model's output, not betting advice.
        """;

    private final ObjectProvider<Client> clientProvider;
    private final AskToolRegistry tools;
    private final boolean enabled;
    private final String model;
    private final long maxTokens;
    private final int maxToolIterations;

    public AskService(ObjectProvider<Client> clientProvider,
                      AskToolRegistry tools,
                      @Value("${app.ai.enabled:false}") boolean enabled,
                      @Value("${app.ai.model:gemini-2.5-flash}") String model,
                      @Value("${app.ai.max-tokens:3000}") long maxTokens,
                      @Value("${app.ai.max-tool-iterations:6}") int maxToolIterations) {
        this.clientProvider = clientProvider;
        this.tools = tools;
        this.enabled = enabled;
        this.model = model;
        this.maxTokens = maxTokens;
        this.maxToolIterations = maxToolIterations;
    }

    /** True when the feature is switched on and a Gemini client bean is wired. */
    public boolean isAvailable() {
        return enabled && clientProvider.getIfAvailable() != null;
    }

    /**
     * Run the question through the tool-use loop, pushing progress + the answer to {@code sink}.
     * Runs on the caller's thread (the controller submits it to a background executor).
     */
    public void ask(String question, AskSink sink) {
        Client client = clientProvider.getIfAvailable();
        if (client == null) {
            sink.error("AI assistant is not configured.");
            return;
        }

        GenerateContentConfig config = GenerateContentConfig.builder()
            .systemInstruction(Content.fromParts(Part.fromText(SYSTEM_PROMPT.formatted(LocalDate.now()))))
            .tools(Tool.builder()
                .functionDeclarations(tools.declarations().toArray(new FunctionDeclaration[0]))
                .build())
            .maxOutputTokens((int) maxTokens)
            .build();

        // The running conversation: the user question, then alternating model tool-call turns and
        // our tool-result turns until the model answers in plain text.
        List<Content> contents = new ArrayList<>();
        contents.add(Content.builder().role("user").parts(Part.fromText(question)).build());

        List<String> used = new ArrayList<>();
        // Deep links derived from the tools the model called, deduped by route, in first-seen order.
        Map<String, LinkRef> links = new LinkedHashMap<>();

        for (int iteration = 0; iteration < maxToolIterations; iteration++) {
            GenerateContentResponse response = client.models.generateContent(model, contents, config);

            List<FunctionCall> calls = response.functionCalls();
            if (calls == null || calls.isEmpty()) {
                String answer = response.text();
                sink.links(new ArrayList<>(links.values()));
                sink.answer(answer == null || answer.isBlank()
                    ? "I couldn't find anything to answer that."
                    : answer.trim());
                sink.sources(used);
                return;
            }

            // Echo the model's tool-call turn, then append one function_response per call.
            response.candidates()
                .flatMap(list -> list.isEmpty() ? java.util.Optional.empty() : list.get(0).content())
                .ifPresent(contents::add);

            List<Part> resultParts = new ArrayList<>();
            for (FunctionCall call : calls) {
                String name = call.name().orElse("");
                sink.status(name, tools.label(name));
                used.add(name);
                Map<String, Object> args = call.args().orElse(Map.of());
                String result = tools.execute(name, args);
                tools.linkFor(name, args, result)
                    .ifPresent(link -> links.putIfAbsent(link.href(), link));
                resultParts.add(Part.fromFunctionResponse(name, Map.of("result", result)));
            }
            contents.add(Content.builder().role("user").parts(resultParts).build());
        }

        sink.error("Reached the tool-call limit before finishing. Try a more specific question.");
    }
}
