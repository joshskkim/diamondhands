package com.diamond.api.ai;

import com.diamond.api.service.OddsMath;
import com.diamond.api.repository.AgentRepository;
import com.diamond.api.repository.UserPreferenceRepository;
import com.google.genai.types.FunctionDeclaration;
import com.google.genai.types.Schema;
import org.springframework.stereotype.Component;

import java.time.LocalDate;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * The agent's WRITE surface. The language model only ever PROPOSES: {@link #propose} validates a
 * tool call into an {@link AgentProposal} (computing the Kelly stake deterministically), the user
 * confirms, and {@link #commit} replays the exact payload. The model never executes a mutation and
 * never invents the stake.
 */
@Component
public class AgentActionRegistry {

    private final UserPreferenceRepository prefsRepo;
    private final AgentRepository agentRepo;
    private final KellyCalculator kelly;

    public AgentActionRegistry(UserPreferenceRepository prefsRepo, AgentRepository agentRepo,
                               KellyCalculator kelly) {
        this.prefsRepo = prefsRepo;
        this.agentRepo = agentRepo;
        this.kelly = kelly;
    }

    public List<String> actionNames() {
        return List.of("set_bankroll", "save_recommendation", "log_bet", "set_line_alert");
    }

    public boolean isAction(String name) {
        return actionNames().contains(name);
    }

    public List<FunctionDeclaration> declarations() {
        return List.of(
            tool("set_bankroll",
                "Set or update the user's bankroll and risk settings (used for Kelly bet sizing). "
                + "Propose this when the user states a bankroll or asks to change risk.",
                props(
                    "bankrollUnits", numProp("Bankroll in units (e.g. 100)."),
                    "unitSizeUsd", numProp("Optional dollars per unit."),
                    "kellyFraction", numProp("Optional fraction of full Kelly, 0-0.5 (default 0.25)."),
                    "riskProfile", strProp("Optional: conservative | balanced | aggressive.")),
                List.of("bankrollUnits")),
            tool("save_recommendation",
                "Save a pick the user wants to track as a Diamond recommendation. Pass the EXACT "
                + "figures you read from get_best_plays (price, book, model and fair probabilities); "
                + "the stake is computed for you from the user's bankroll. Never invent these.",
                props(
                    "gameId", strProp("Game id (as a string)."),
                    "market", strProp("total | moneyline | run_line | hit | hr."),
                    "side", strProp("over | under | home | away."),
                    "line", numProp("The line (omit for moneyline)."),
                    "playerId", strProp("Player id for props (omit for game markets)."),
                    "playerName", strProp("Player name for props."),
                    "priceAmerican", numProp("American price (e.g. -110, +130)."),
                    "book", strProp("Sportsbook the price is from."),
                    "modelProb", numProp("Model probability 0-1 from the tool result."),
                    "fairProb", numProp("De-vigged fair probability 0-1 from the tool result."),
                    "confidence", numProp("Optional calibrated confidence 0-1 (e.g. the judge's verdict).")),
                List.of("gameId", "market", "side", "priceAmerican", "modelProb", "fairProb")),
            tool("log_bet",
                "Log a bet the user actually placed into their personal tracker (graded later for "
                + "their own ROI/CLV). Pass the stake the user told you, not a computed one.",
                props(
                    "gameId", strProp("Game id (as a string)."),
                    "market", strProp("total | moneyline | run_line | hit | hr."),
                    "side", strProp("over | under | home | away."),
                    "line", numProp("The line (omit for moneyline)."),
                    "playerId", strProp("Player id for props."),
                    "playerName", strProp("Player name for props."),
                    "stakeUnits", numProp("Units staked."),
                    "priceAmerican", numProp("American price taken."),
                    "book", strProp("Sportsbook.")),
                List.of("gameId", "market", "side", "stakeUnits", "priceAmerican")),
            tool("set_line_alert",
                "Arm an alert for when a selection reaches a target price or edge.",
                props(
                    "gameId", strProp("Game id (as a string)."),
                    "market", strProp("Market."),
                    "side", strProp("Side."),
                    "line", numProp("Line."),
                    "playerId", strProp("Player id for props."),
                    "targetPriceAmerican", numProp("Alert when the price reaches this American number."),
                    "targetEdge", numProp("Alert when the model edge reaches this (0-1).")),
                List.of("market", "side")));
    }

    public String label(String name) {
        return switch (name) {
            case "set_bankroll" -> "Updating your bankroll settings…";
            case "save_recommendation" -> "Preparing a pick to save…";
            case "log_bet" -> "Logging your bet…";
            case "set_line_alert" -> "Arming a line alert…";
            default -> "Preparing an action…";
        };
    }

    // ── propose (validate -> human-confirmable proposal) ─────────────────────────

    /** Validate a write tool call into a proposal. Throws IllegalArgumentException on bad input. */
    public AgentProposal propose(String name, Map<String, Object> args, UserPreferences prefs) {
        return switch (name) {
            case "set_bankroll" -> proposeBankroll(args, prefs);
            case "save_recommendation" -> proposeSaveRec(args, prefs);
            case "log_bet" -> proposeLogBet(args);
            case "set_line_alert" -> proposeLineAlert(args);
            default -> throw new IllegalArgumentException("unknown action: " + name);
        };
    }

    private AgentProposal proposeBankroll(Map<String, Object> args, UserPreferences prefs) {
        double bankroll = reqDouble(args, "bankrollUnits");
        if (bankroll <= 0) {
            throw new IllegalArgumentException("bankroll must be positive");
        }
        Double unit = optDouble(args, "unitSizeUsd");
        double frac = KellyCalculator.clampFraction(
            optDouble(args, "kellyFraction") != null ? optDouble(args, "kellyFraction") : prefs.kellyFraction());
        String risk = optStr(args, "riskProfile") != null ? optStr(args, "riskProfile") : prefs.riskProfile();
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("bankrollUnits", bankroll);
        payload.put("unitSizeUsd", unit);
        payload.put("kellyFraction", frac);
        payload.put("riskProfile", risk);
        String summary = String.format("Set bankroll to %.0f units at %.0f%%-Kelly (%s).",
            bankroll, frac * 100, risk);
        return new AgentProposal("set_bankroll", summary, payload);
    }

    private AgentProposal proposeSaveRec(Map<String, Object> args, UserPreferences prefs) {
        long gameId = reqLong(args, "gameId");
        String market = reqStr(args, "market");
        String side = reqStr(args, "side");
        int price = (int) reqDouble(args, "priceAmerican");
        double modelProb = reqDouble(args, "modelProb");
        double fairProb = reqDouble(args, "fairProb");
        if (modelProb <= 0 || modelProb >= 1 || fairProb <= 0 || fairProb >= 1) {
            throw new IllegalArgumentException("probabilities must be between 0 and 1");
        }
        double decimal = OddsMath.americanToDecimal(price);
        double edge = modelProb - fairProb;
        double evPct = OddsMath.ev(modelProb, decimal);

        Double stake = null;
        String sizeNote = "sizing disabled (set a bankroll first)";
        if (prefs.canSize()) {
            KellyCalculator.Sizing s = kelly.size(modelProb, decimal, prefs.bankrollUnits(),
                prefs.unitSizeUsd(), prefs.kellyFraction());
            stake = s.stakeUnits();
            sizeNote = String.format("%.2f units (%s)", s.stakeUnits(), s.note());
        }

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("gameId", gameId);
        payload.put("market", market);
        payload.put("side", side);
        payload.put("line", optDouble(args, "line"));
        payload.put("playerId", optInt(args, "playerId"));
        payload.put("playerName", optStr(args, "playerName"));
        payload.put("priceAmerican", price);
        payload.put("book", optStr(args, "book"));
        payload.put("modelProb", round4(modelProb));
        payload.put("fairProb", round4(fairProb));
        payload.put("edge", round4(edge));
        payload.put("evPct", round4(evPct));
        payload.put("stakeUnits", stake);
        payload.put("confidence", optDouble(args, "confidence"));

        String who = optStr(args, "playerName") != null ? optStr(args, "playerName") : ("game " + gameId);
        String summary = String.format("Save %s %s %s%s @ %+d — edge %.1f%%, EV %.1f%%; stake %s.",
            who, market, side, optDouble(args, "line") != null ? " " + optDouble(args, "line") : "",
            price, edge * 100, evPct * 100, sizeNote);
        return new AgentProposal("save_recommendation", summary, payload);
    }

    private AgentProposal proposeLogBet(Map<String, Object> args) {
        long gameId = reqLong(args, "gameId");
        String market = reqStr(args, "market");
        String side = reqStr(args, "side");
        double stake = reqDouble(args, "stakeUnits");
        int price = (int) reqDouble(args, "priceAmerican");
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("gameId", gameId);
        payload.put("market", market);
        payload.put("side", side);
        payload.put("line", optDouble(args, "line"));
        payload.put("playerId", optInt(args, "playerId"));
        payload.put("playerName", optStr(args, "playerName"));
        payload.put("stakeUnits", stake);
        payload.put("priceAmerican", price);
        payload.put("book", optStr(args, "book"));
        String summary = String.format("Log bet: %s %s @ %+d for %.2f units.", market, side, price, stake);
        return new AgentProposal("log_bet", summary, payload);
    }

    private AgentProposal proposeLineAlert(Map<String, Object> args) {
        String market = reqStr(args, "market");
        String side = reqStr(args, "side");
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("gameId", optLong(args, "gameId"));
        payload.put("market", market);
        payload.put("side", side);
        payload.put("line", optDouble(args, "line"));
        payload.put("playerId", optInt(args, "playerId"));
        payload.put("targetPriceAmerican", optInt(args, "targetPriceAmerican"));
        payload.put("targetEdge", optDouble(args, "targetEdge"));
        String summary = String.format("Alert on %s %s when it hits your target.", market, side);
        return new AgentProposal("set_line_alert", summary, payload);
    }

    // ── commit (replay a confirmed payload) ──────────────────────────────────────

    public String commit(String action, Map<String, Object> p, long userId) {
        LocalDate slate = LocalDate.now();
        return switch (action) {
            case "set_bankroll" -> {
                UserPreferences cur = prefsRepo.findOrDefault(userId);
                prefsRepo.upsert(new UserPreferences(userId,
                    asDouble(p.get("bankrollUnits")), asDouble(p.get("unitSizeUsd")),
                    asDouble(p.get("kellyFraction")) != null ? asDouble(p.get("kellyFraction")) : cur.kellyFraction(),
                    p.get("riskProfile") != null ? p.get("riskProfile").toString() : cur.riskProfile(),
                    cur.briefingChannel(), cur.discordWebhookUrl()));
                yield "Bankroll updated.";
            }
            case "save_recommendation" -> {
                long id = agentRepo.insertRecommendation(null, userId, slate,
                    asLong(p.get("gameId")), str(p.get("market")), str(p.get("side")),
                    asDouble(p.get("line")), asInteger(p.get("playerId")), str(p.get("playerName")),
                    asDouble(p.get("modelProb")), asDouble(p.get("fairProb")), asDouble(p.get("edge")),
                    asDouble(p.get("evPct")), asInteger(p.get("priceAmerican")), str(p.get("book")),
                    asDouble(p.get("stakeUnits")), asDouble(p.get("confidence")));
                yield "Saved recommendation #" + id + ". It'll be graded after the game (with CLV).";
            }
            case "log_bet" -> {
                agentRepo.upsertUserBet(userId, slate, asLong(p.get("gameId")), str(p.get("market")),
                    str(p.get("side")), asDouble(p.get("line")), asInteger(p.get("playerId")),
                    str(p.get("playerName")), asDouble(p.get("stakeUnits")),
                    asInteger(p.get("priceAmerican")), str(p.get("book")));
                yield "Bet logged to your tracker.";
            }
            case "set_line_alert" -> {
                long id = agentRepo.insertLineAlert(userId, slate, asLong(p.get("gameId")),
                    str(p.get("market")), str(p.get("side")), asDouble(p.get("line")),
                    asInteger(p.get("playerId")), asInteger(p.get("targetPriceAmerican")),
                    asDouble(p.get("targetEdge")));
                yield "Line alert #" + id + " armed.";
            }
            default -> throw new IllegalArgumentException("unknown action: " + action);
        };
    }

    // ── arg helpers ──────────────────────────────────────────────────────────────

    private static Double round4(double v) {
        return Math.round(v * 10000.0) / 10000.0;
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

    private static Integer asInteger(Object o) {
        Double d = asDouble(o);
        return d == null ? null : d.intValue();
    }

    private static String optStr(Map<String, Object> in, String key) {
        Object v = in.get(key);
        if (v == null) return null;
        if (v instanceof Number n) {
            double d = n.doubleValue();
            return (d == Math.floor(d) && !Double.isInfinite(d)) ? Long.toString((long) d) : n.toString();
        }
        String s = v.toString();
        return s.isBlank() ? null : s;
    }

    private static String reqStr(Map<String, Object> in, String key) {
        String s = optStr(in, key);
        if (s == null) throw new IllegalArgumentException("missing required '" + key + "'");
        return s.trim();
    }

    private static Double optDouble(Map<String, Object> in, String key) {
        return asDouble(in.get(key));
    }

    private static double reqDouble(Map<String, Object> in, String key) {
        Double d = asDouble(in.get(key));
        if (d == null) throw new IllegalArgumentException("missing/invalid numeric '" + key + "'");
        return d;
    }

    private static Long optLong(Map<String, Object> in, String key) {
        return asLong(in.get(key));
    }

    private static Integer optInt(Map<String, Object> in, String key) {
        return asInteger(in.get(key));
    }

    private static long reqLong(Map<String, Object> in, String key) {
        Long l = asLong(in.get(key));
        if (l == null) throw new IllegalArgumentException("missing/invalid id '" + key + "'");
        return l;
    }

    // ── declaration builders ─────────────────────────────────────────────────────

    private static Map<String, Schema> props(Object... kv) {
        Map<String, Schema> m = new LinkedHashMap<>();
        for (int i = 0; i < kv.length; i += 2) {
            m.put((String) kv[i], (Schema) kv[i + 1]);
        }
        return m;
    }

    private static FunctionDeclaration tool(String name, String description,
                                            Map<String, Schema> properties, List<String> required) {
        Schema params = Schema.builder()
            .type("OBJECT").properties(properties).required(required.toArray(new String[0])).build();
        return FunctionDeclaration.builder().name(name).description(description).parameters(params).build();
    }

    private static Schema strProp(String d) {
        return Schema.builder().type("STRING").description(d).build();
    }

    private static Schema numProp(String d) {
        return Schema.builder().type("NUMBER").description(d).build();
    }
}
