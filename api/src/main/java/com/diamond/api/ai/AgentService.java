package com.diamond.api.ai;

import com.diamond.api.repository.AgentRepository;
import com.diamond.api.repository.UserPreferenceRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.google.genai.Client;
import com.google.genai.types.Content;
import com.google.genai.types.FunctionDeclaration;
import com.google.genai.types.Part;
import com.google.genai.types.Schema;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * The Diamond Analyst — a stateful, authenticated upgrade of "Ask Diamond". It runs the same
 * bounded Gemini tool loop but: (1) loads the user's bankroll/risk preferences (long-term memory),
 * (2) can spin up a Bull/Skeptic/Judge {@link DebateOrchestrator debate} on a candidate pick,
 * (3) can PROPOSE write actions (save a pick, log a bet, set bankroll/alert) that the user must
 * confirm, and (4) logs every decision to the trajectory ({@code agent_runs}/{@code agent_steps})
 * so the eval harness can grade it. {@link AskService} stays the public, stateless path.
 */
@Service
public class AgentService {

    private static final String SYSTEM_PROMPT = """
        You are the Diamond Analyst — a personal baseball betting co-pilot for a stats-first
        projection app. Today is %s. Answer using ONLY the tools, which read the app's real
        projections, odds/EV, sim, and the user's settings.

        User settings: %s

        How to work:
        - Ground every claim in tool results. Never invent players, games, numbers, or lines.
        - When the user wants a verdict on a specific pick (or you're recommending one), call
          debate_pick to run a bull-vs-skeptic debate and use the judge's confidence in your answer.
        - To size a bet, the user needs a bankroll set. If they ask for sizing and have none, call
          set_bankroll (proposing it) or ask them for one — never guess a stake yourself.
        - Writes (set_bankroll, save_recommendation, log_bet, set_line_alert) only PROPOSE an
          action; the user confirms it. After proposing, tell the user what you queued up.
        - Be concise and lead with the answer. Probabilities are 0-1 unless shown as a price.
        - This is informational analysis of a model's output, not betting advice.
        """;

    private final ObjectProvider<Client> clientProvider;
    private final AskToolRegistry readTools;
    private final AgentActionRegistry actions;
    private final DebateOrchestrator debate;
    private final ActionTokenService tokens;
    private final GeminiToolLoop loop;
    private final AgentRepository agentRepo;
    private final UserPreferenceRepository prefsRepo;
    private final ObjectMapper mapper;
    private final boolean enabled;
    private final String model;
    private final long maxTokens;
    private final int maxToolIterations;
    private final int historyTurns;

    public AgentService(ObjectProvider<Client> clientProvider, AskToolRegistry readTools,
                        AgentActionRegistry actions, DebateOrchestrator debate, ActionTokenService tokens,
                        GeminiToolLoop loop, AgentRepository agentRepo, UserPreferenceRepository prefsRepo,
                        ObjectMapper mapper,
                        @Value("${app.ai.enabled:false}") boolean enabled,
                        @Value("${app.ai.model:gemini-2.5-flash}") String model,
                        @Value("${app.ai.max-tokens:3000}") long maxTokens,
                        @Value("${app.agent.max-tool-iterations:8}") int maxToolIterations,
                        @Value("${app.agent.history-turns:6}") int historyTurns) {
        this.clientProvider = clientProvider;
        this.readTools = readTools;
        this.actions = actions;
        this.debate = debate;
        this.tokens = tokens;
        this.loop = loop;
        this.agentRepo = agentRepo;
        this.prefsRepo = prefsRepo;
        this.mapper = mapper;
        this.enabled = enabled;
        this.model = model;
        this.maxTokens = maxTokens;
        this.maxToolIterations = maxToolIterations;
        this.historyTurns = historyTurns;
    }

    public boolean isAvailable() {
        return enabled && clientProvider.getIfAvailable() != null;
    }

    /** Run a question for an authenticated user through the agentic loop, in a conversation thread. */
    public void ask(long userId, Long threadId, String question, AgentSink sink) {
        Client client = clientProvider.getIfAvailable();
        if (client == null) {
            sink.error("AI assistant is not configured.");
            return;
        }
        // Resolve the thread: reuse the caller's if it's theirs, else start a new one. The id is
        // sent back so the client threads the next turn onto the same conversation.
        long tid = (threadId != null && agentRepo.ownsThread(threadId, userId))
            ? threadId : agentRepo.createThread(userId);
        sink.thread(tid);

        // Replay the thread's recent turns so follow-ups ("size that one") resolve in context.
        List<Content> history = new ArrayList<>();
        for (AgentRepository.Turn t : agentRepo.recentTurns(tid, historyTurns)) {
            history.add(Content.builder().role("user").parts(Part.fromText(t.question())).build());
            history.add(Content.builder().role("model").parts(Part.fromText(t.answer())).build());
        }

        UserPreferences prefs = prefsRepo.findOrDefault(userId);
        long runId = agentRepo.createRun("web", userId, tid, question, model);
        AtomicInteger stepNo = new AtomicInteger();

        GeminiToolLoop.Steps steps = (role, tool, args, summary, ms) ->
            agentRepo.addStep(runId, stepNo.incrementAndGet(), role, tool, toJson(args), summary, ms);

        List<FunctionDeclaration> decls = new ArrayList<>(readTools.declarations());
        decls.add(debatePickDecl());
        decls.addAll(actions.declarations());

        GeminiToolLoop.Executor exec = (name, args) -> {
            if ("debate_pick".equals(name)) {
                DebateOrchestrator.Verdict v = debate.debate(client, candidateOf(args), sink, steps);
                return toJson(Map.of(
                    "confidence", v.confidence(), "verdict", v.verdict(),
                    "rationale", v.rationale(), "keyRisks", v.keyRisks()));
            }
            if (actions.isAction(name)) {
                try {
                    AgentProposal proposal = actions.propose(name, args, prefs);
                    String token = tokens.sign(proposal, userId);
                    sink.confirm(token, proposal);
                    return toJson(Map.of("status", "awaiting_user_confirmation", "summary", proposal.summary()));
                } catch (IllegalArgumentException e) {
                    return "{\"error\":\"" + escape(e.getMessage()) + "\"}";
                }
            }
            return readTools.execute(name, args);
        };

        GeminiToolLoop.Labeler labeler = name -> {
            if ("debate_pick".equals(name)) {
                return "Running a bull vs. skeptic debate…";
            }
            return actions.isAction(name) ? actions.label(name) : readTools.label(name);
        };

        try {
            GeminiToolLoop.Result result = loop.run(client, model, "model",
                SYSTEM_PROMPT.formatted(LocalDate.now(), describePrefs(prefs)),
                decls, exec, labeler, readTools::linkFor,
                history, question, maxToolIterations, maxTokens, sink::status, steps);

            if (result.hitLimit()) {
                agentRepo.finishRun(runId, null, "error", result.toolCalls());
                sink.error("Reached the tool-call limit before finishing. Try a more specific question.");
                return;
            }
            String answer = result.text().isBlank() ? "I couldn't find anything to answer that." : result.text();
            sink.links(result.links());
            sink.answer(answer);
            sink.sources(result.toolsUsed());
            agentRepo.finishRun(runId, answer, "done", result.toolCalls());
            agentRepo.touchThread(tid);
        } catch (Exception e) {
            agentRepo.finishRun(runId, null, "error", 0);
            sink.error("Something went wrong answering that.");
        }
    }

    /** Execute a user-confirmed write action (replays the signed payload; no model involved). */
    public String confirm(long userId, String token) {
        return tokens.verify(token, userId)
            .map(v -> actions.commit(v.action(), v.payload(), userId))
            .orElseThrow(() -> new IllegalArgumentException("invalid or expired confirmation"));
    }

    // ── helpers ──────────────────────────────────────────────────────────────────

    private DebateOrchestrator.Candidate candidateOf(Map<String, Object> a) {
        return new DebateOrchestrator.Candidate(
            asLong(a.get("gameId")) != null ? asLong(a.get("gameId")) : 0L,
            str(a.get("market")), str(a.get("side")), asDouble(a.get("line")),
            asInt(a.get("playerId")), str(a.get("playerName")), asInt(a.get("priceAmerican")),
            asDouble(a.get("modelProb")), asDouble(a.get("fairProb")));
    }

    private static String describePrefs(UserPreferences p) {
        if (!p.canSize()) {
            return "no bankroll set (sizing disabled until the user sets one); risk=" + p.riskProfile();
        }
        return String.format("bankroll=%.0f units, %.0f%%-Kelly, risk=%s",
            p.bankrollUnits(), p.kellyFraction() * 100, p.riskProfile());
    }

    private FunctionDeclaration debatePickDecl() {
        Map<String, Schema> props = new LinkedHashMap<>();
        props.put("gameId", strProp("Game id (as a string)."));
        props.put("market", strProp("total | moneyline | run_line | hit | hr."));
        props.put("side", strProp("over | under | home | away."));
        props.put("line", numProp("The line (omit for moneyline)."));
        props.put("playerId", strProp("Player id for props."));
        props.put("playerName", strProp("Player name for props."));
        props.put("priceAmerican", numProp("American price."));
        props.put("modelProb", numProp("Model probability 0-1."));
        props.put("fairProb", numProp("Fair probability 0-1."));
        Schema params = Schema.builder().type("OBJECT").properties(props)
            .required("gameId", "market", "side").build();
        return FunctionDeclaration.builder()
            .name("debate_pick")
            .description("Run a bull-vs-skeptic-vs-judge debate on a candidate pick and get a "
                + "calibrated confidence + verdict (bet/lean/pass). Pass the figures you read from "
                + "get_best_plays. Use this before recommending or saving a pick.")
            .parameters(params)
            .build();
    }

    private String toJson(Object o) {
        try {
            return mapper.writeValueAsString(o);
        } catch (Exception e) {
            return "{}";
        }
    }

    private static String escape(String s) {
        return s == null ? "" : s.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    private static String str(Object o) {
        return o == null ? null : o.toString();
    }

    private static Double asDouble(Object o) {
        if (o == null) return null;
        if (o instanceof Number n) return n.doubleValue();
        try {
            return Double.parseDouble(o.toString());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static Long asLong(Object o) {
        Double d = asDouble(o);
        return d == null ? null : d.longValue();
    }

    private static Integer asInt(Object o) {
        Double d = asDouble(o);
        return d == null ? null : d.intValue();
    }

    private static Schema strProp(String d) {
        return Schema.builder().type("STRING").description(d).build();
    }

    private static Schema numProp(String d) {
        return Schema.builder().type("NUMBER").description(d).build();
    }
}
