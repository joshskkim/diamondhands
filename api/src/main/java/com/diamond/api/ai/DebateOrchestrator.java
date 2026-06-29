package com.diamond.api.ai;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.google.genai.Client;
import com.google.genai.types.Content;
import com.google.genai.types.GenerateContentConfig;
import com.google.genai.types.GenerateContentResponse;
import com.google.genai.types.Part;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * The Bull / Skeptic / Judge reasoning engine (anchor F). Specialisation is genuine, not
 * decorative: the bull argues FOR a candidate using the general read tools, the skeptic
 * challenges it using the SAME contrarian signals the Model's Picks bar vetoes on
 * ({@link SkepticToolRegistry}), and a judge synthesises a calibrated confidence + verdict. Each
 * role's tool calls land in the trajectory log; the judge's verdict drives what gets saved.
 */
@Component
public class DebateOrchestrator {

    private static final String BULL_PROMPT = """
        You are the BULL in a betting debate. Argue the strongest HONEST case FOR this pick using
        the tools (projections, EV/edge board, prop board, player form). Cite real figures only —
        never invent a number. 3-5 tight sentences. End with your single best supporting fact.
        """;

    private static final String SKEPTIC_PROMPT = """
        You are the SKEPTIC in a betting debate. Challenge this pick using your contrarian tools:
        does the Monte-Carlo sim disagree? Does the hit-rate traffic light contradict it? Is our
        price an outlier across books, or has the line moved against us? Is the edge built on a thin
        recent sample? Cite real figures only — never invent. 3-5 tight sentences. End with the
        single biggest reason to pass.
        """;

    private static final String JUDGE_PROMPT = """
        You are the JUDGE. Weigh the bull's case against the skeptic's. Output STRICT JSON only,
        no prose, with this shape:
        {"confidence": <0-1>, "verdict": "<bet|lean|pass>", "rationale": "<one sentence>",
         "keyRisks": ["<short>", "..."]}
        confidence is your calibrated probability the pick wins. Be willing to say pass.
        """;

    /** A pick under debate. */
    public record Candidate(long gameId, String market, String side, Double line, Integer playerId,
                            String playerName, Integer priceAmerican, Double modelProb, Double fairProb) {
        String describe() {
            String who = playerName != null ? playerName : ("game " + gameId);
            return String.format("Candidate: %s — %s %s%s @ %s. model=%.3f fair=%.3f.",
                who, market, side, line != null ? " " + line : "",
                priceAmerican != null ? String.format("%+d", priceAmerican) : "n/a",
                modelProb != null ? modelProb : 0.0, fairProb != null ? fairProb : 0.0);
        }
    }

    public record Verdict(double confidence, String verdict, String rationale, List<String> keyRisks) {}

    private final GeminiToolLoop loop;
    private final AskToolRegistry bullTools;
    private final SkepticToolRegistry skepticTools;
    private final ObjectMapper mapper;
    private final String model;
    private final String judgeModel;
    private final int maxIters;
    private final long maxTokens;

    public DebateOrchestrator(GeminiToolLoop loop, AskToolRegistry bullTools,
                              SkepticToolRegistry skepticTools, ObjectMapper mapper,
                              @Value("${app.ai.model:gemini-2.5-flash}") String model,
                              @Value("${app.agent.judge-model:gemini-2.5-pro}") String judgeModel,
                              @Value("${app.agent.debate-tool-iterations:3}") int maxIters,
                              @Value("${app.ai.max-tokens:3000}") long maxTokens) {
        this.loop = loop;
        this.bullTools = bullTools;
        this.skepticTools = skepticTools;
        this.mapper = mapper;
        this.model = model;
        this.judgeModel = judgeModel;
        this.maxIters = maxIters;
        this.maxTokens = maxTokens;
    }

    /** Run the three-role debate, streaming each turn, and return the judge's verdict. */
    public Verdict debate(Client client, Candidate c, AgentSink sink, GeminiToolLoop.Steps steps) {
        String candidate = c.describe();
        GeminiToolLoop.Status status = sink::status;

        GeminiToolLoop.Result bull = loop.run(client, model, "bull", BULL_PROMPT,
            bullTools.declarations(), bullTools::execute, bullTools::label, bullTools::linkFor,
            candidate, maxIters, maxTokens, status, steps);
        sink.role("bull", bull.text());

        String skepticInput = candidate + "\n\nThe bull argues:\n" + bull.text();
        GeminiToolLoop.Result skeptic = loop.run(client, model, "skeptic", SKEPTIC_PROMPT,
            skepticTools.declarations(), skepticTools::execute, skepticTools::label, skepticTools::linkFor,
            skepticInput, maxIters, maxTokens, status, steps);
        sink.role("skeptic", skeptic.text());

        Verdict verdict = judge(client, candidate, bull.text(), skeptic.text());
        sink.role("judge", verdict.verdict().toUpperCase() + " (confidence "
            + String.format("%.0f%%", verdict.confidence() * 100) + "): " + verdict.rationale());
        if (steps != null) {
            steps.step("judge", "judge_verdict", Map.of("candidate", candidate),
                safeJson(verdict), 0L);
        }
        return verdict;
    }

    private Verdict judge(Client client, String candidate, String bull, String skeptic) {
        String input = candidate + "\n\nBULL:\n" + bull + "\n\nSKEPTIC:\n" + skeptic;
        GenerateContentConfig config = GenerateContentConfig.builder()
            .systemInstruction(Content.fromParts(Part.fromText(JUDGE_PROMPT)))
            .maxOutputTokens((int) maxTokens)
            .responseMimeType("application/json")
            .build();
        List<Content> contents = new ArrayList<>();
        contents.add(Content.builder().role("user").parts(Part.fromText(input)).build());
        GenerateContentResponse response = client.models.generateContent(judgeModel, contents, config);
        return parseVerdict(response.text());
    }

    private Verdict parseVerdict(String text) {
        try {
            JsonNode n = mapper.readTree(text);
            double conf = n.path("confidence").asDouble(0.5);
            String verdict = n.path("verdict").asText("pass");
            String rationale = n.path("rationale").asText("");
            List<String> risks = new ArrayList<>();
            if (n.path("keyRisks").isArray()) {
                n.path("keyRisks").forEach(r -> risks.add(r.asText()));
            }
            return new Verdict(Math.max(0, Math.min(1, conf)), verdict, rationale, risks);
        } catch (Exception e) {
            return new Verdict(0.5, "pass", "Judge could not reach a clear verdict.", List.of());
        }
    }

    private String safeJson(Verdict v) {
        try {
            return mapper.writeValueAsString(v);
        } catch (Exception e) {
            return "{}";
        }
    }
}
