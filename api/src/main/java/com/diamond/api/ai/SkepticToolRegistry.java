package com.diamond.api.ai;

import com.diamond.api.service.MostLikelyService;
import com.diamond.api.service.OddsService;
import com.diamond.api.repository.PlayerStatRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.google.genai.types.FunctionDeclaration;
import com.google.genai.types.Schema;
import org.springframework.stereotype.Component;

import java.time.LocalDate;
import java.util.List;
import java.util.Map;

/**
 * The skeptic's tool surface: read-only tools that surface the contrarian signals the
 * Model's Picks bar (ingester {@code picks.py::build_picks}) already vetoes on, so the
 * skeptic's challenges are grounded in the same data, never invented:
 *   · sim disagreement      -> {@link MostLikelyService} totals/props ( _sim_totals_veto )
 *   · hit-rate traffic light -> {@link OddsService#hitRates} ( HIT_RATE_VETO_BANDS )
 *   · line movement / shop   -> {@link OddsService#lineShop} (is our price the outlier?)
 *   · small sample           -> {@link PlayerStatRepository#findRecent} game count
 */
@Component
public class SkepticToolRegistry implements ToolRegistry {

    private static final int RECENT_GAMES = 20;

    private final OddsService odds;
    private final MostLikelyService mostLikely;
    private final PlayerStatRepository players;
    private final ObjectMapper mapper;

    public SkepticToolRegistry(OddsService odds, MostLikelyService mostLikely,
                               PlayerStatRepository players, ObjectMapper mapper) {
        this.odds = odds;
        this.mostLikely = mostLikely;
        this.players = players;
        this.mapper = mapper;
    }

    @Override
    public List<FunctionDeclaration> declarations() {
        Map<String, Schema> dateOnly = Map.of("date", strProp("Slate date YYYY-MM-DD. Omit for today."));
        return List.of(
            tool("check_sim_disagreement",
                "The Monte-Carlo game simulator's board (totals vs the line, NRFI, top props). Use it "
                + "to see whether the independent sim DISAGREES with a pick — sim landing the other "
                + "way on a total is the model's own veto signal.",
                dateOnly, List.of()),
            tool("check_hit_rate_traffic_light",
                "Per-prop season clear rates (the 'traffic light'): how often a player actually clears "
                + "this line over L5/L10/L20/season. An over on a player who rarely clears (or an under "
                + "on one who usually does) is a red flag.",
                dateOnly, List.of()),
            tool("check_line_movement",
                "Multi-book price ladder per selection. Use it to see if our price is an outlier (only "
                + "one book offers the edge) or if the market has moved against the pick.",
                dateOnly, List.of()),
            tool("check_recent_sample",
                "A player's recent game log (PA, hits, HR, K, xwOBA). Use it to judge whether the edge "
                + "rests on a thin or volatile sample. Needs a playerId.",
                Map.of("playerId", strProp("The player's numeric id (as a string).")),
                List.of("playerId")));
    }

    @Override
    public String label(String name) {
        return switch (name) {
            case "check_sim_disagreement" -> "Cross-checking the game simulator…";
            case "check_hit_rate_traffic_light" -> "Reading the hit-rate traffic light…";
            case "check_line_movement" -> "Line-shopping across books…";
            case "check_recent_sample" -> "Sizing up the recent-form sample…";
            default -> "Stress-testing the pick…";
        };
    }

    @Override
    public String execute(String name, Map<String, Object> args) {
        try {
            return switch (name) {
                case "check_sim_disagreement" -> json(mostLikely.board(date(args)));
                case "check_hit_rate_traffic_light" -> json(odds.hitRates(date(args)));
                case "check_line_movement" -> json(odds.lineShop(date(args)));
                case "check_recent_sample" -> json(players.findRecent(reqInt(args, "playerId"), RECENT_GAMES));
                default -> error("unknown tool: " + name);
            };
        } catch (IllegalArgumentException e) {
            return error(e.getMessage());
        } catch (Exception e) {
            return error("tool '" + name + "' failed: " + e.getMessage());
        }
    }

    // ── helpers (mirror AskToolRegistry's conventions) ───────────────────────────

    private String json(Object o) {
        try {
            return mapper.writeValueAsString(o);
        } catch (Exception e) {
            return error("serialization failed");
        }
    }

    private static String error(String message) {
        return "{\"error\":\"" + (message == null ? "" : message.replace("\\", "\\\\").replace("\"", "\\\"")) + "\"}";
    }

    private static LocalDate date(Map<String, Object> in) {
        String s = optStr(in, "date");
        return (s == null || s.isBlank()) ? LocalDate.now() : LocalDate.parse(s.trim());
    }

    private static String optStr(Map<String, Object> in, String key) {
        Object v = in.get(key);
        if (v == null) {
            return null;
        }
        if (v instanceof Number n) {
            double d = n.doubleValue();
            return (d == Math.floor(d) && !Double.isInfinite(d)) ? Long.toString((long) d) : n.toString();
        }
        return v.toString();
    }

    private static int reqInt(Map<String, Object> in, String key) {
        String s = optStr(in, key);
        if (s == null || s.isBlank()) {
            throw new IllegalArgumentException("missing required parameter '" + key + "'");
        }
        try {
            return Math.toIntExact(Long.parseLong(s.trim()));
        } catch (NumberFormatException e) {
            throw new IllegalArgumentException("parameter '" + key + "' must be a number");
        }
    }

    private static FunctionDeclaration tool(String name, String description,
                                            Map<String, Schema> properties, List<String> required) {
        Schema params = Schema.builder()
            .type("OBJECT").properties(properties).required(required.toArray(new String[0])).build();
        return FunctionDeclaration.builder().name(name).description(description).parameters(params).build();
    }

    private static Schema strProp(String description) {
        return Schema.builder().type("STRING").description(description).build();
    }
}
