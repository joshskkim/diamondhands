package com.diamond.api.ai;

import com.google.genai.types.FunctionDeclaration;
import com.google.genai.types.Schema;
import com.fasterxml.jackson.databind.JsonNode;
import com.diamond.api.dto.PlayerDetailDto;
import com.diamond.api.service.AccuracyService;
import com.diamond.api.service.GameService;
import com.diamond.api.service.MostLikelyService;
import com.diamond.api.service.OddsService;
import com.diamond.api.service.ProjectionService;
import com.diamond.api.service.PropBoardService;
import com.diamond.api.service.TennisService;
import com.diamond.api.repository.PlayerStatRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Component;

import java.time.LocalDate;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * The tool surface the "Ask Diamond" model can call. Each tool is a thin read-only wrapper
 * over an existing {@code service}/{@code repository} method, returning JSON. Keeping the set
 * small and grounded in already-cached services is deliberate: the model can only answer from
 * real data the app already serves, never from arbitrary SQL or its own guesses.
 */
@Component
public class AskToolRegistry {

    private static final int BEST_PLAYS_CAP = 15;
    private static final int PLAYER_SEARCH_CAP = 8;
    private static final int PLAYER_RECENT_GAMES = 15;

    private final GameService games;
    private final ProjectionService projections;
    private final OddsService odds;
    private final PropBoardService propBoard;
    private final MostLikelyService mostLikely;
    private final AccuracyService accuracy;
    private final TennisService tennis;
    private final PlayerStatRepository players;
    private final ObjectMapper mapper;

    public AskToolRegistry(GameService games, ProjectionService projections, OddsService odds,
                           PropBoardService propBoard, MostLikelyService mostLikely,
                           AccuracyService accuracy, TennisService tennis,
                           PlayerStatRepository players, ObjectMapper mapper) {
        this.games = games;
        this.projections = projections;
        this.odds = odds;
        this.propBoard = propBoard;
        this.mostLikely = mostLikely;
        this.accuracy = accuracy;
        this.tennis = tennis;
        this.players = players;
        this.mapper = mapper;
    }

    // ── Tool definitions (the model's menu) ─────────────────────────────────────

    public List<FunctionDeclaration> declarations() {
        Map<String, Schema> dateOnly = Map.of(
            "date", strProp("Slate date as YYYY-MM-DD. Omit for today."));
        return List.of(
            tool("get_today_games",
                "List today's MLB games (matchup, teams, start time, probable starters).",
                Map.of(), List.of()),
            tool("get_game_projections",
                "Per-batter projections for one MLB game: hit/HR/TB probabilities, expected PA, "
                + "matchup quality, and pitch-arsenal edges. Needs a gameId from get_today_games.",
                Map.of("gameId", strProp("The game's numeric id (as a string).")),
                List.of("gameId")),
            tool("get_best_plays",
                "Top sportsbook bets on the slate ranked by the model's edge over the de-vigged "
                + "fair line (game markets + batter props), with EV%, best book, and price.",
                dateOnly, List.of()),
            tool("get_prop_board",
                "The model's single most-likely batter per market (hit / HR / total bases / "
                + "strikeout) plus top pitcher prop picks, with the reasoning behind each.",
                dateOnly, List.of()),
            tool("get_most_likely",
                "Game-simulator board: full-game totals vs the line (edge, P(over)), NRFI/YRFI, "
                + "first-five-innings markets, and the top player props.",
                dateOnly, List.of()),
            tool("search_player",
                "Find MLB players by (partial) name. Returns up to " + PLAYER_SEARCH_CAP
                + " matches with their numeric playerId, team, and position.",
                Map.of("name", strProp("Full or partial player name.")),
                List.of("name")),
            tool("get_player",
                "One MLB player's details plus their recent game log (PA, hits, HR, K, xwOBA). "
                + "Needs a playerId from search_player.",
                Map.of("playerId", strProp("The player's numeric id (as a string).")),
                List.of("playerId")),
            tool("get_tennis_matches_today",
                "Today's scheduled ATP matches with surface-blended win probabilities and "
                + "best-line EV.",
                Map.of(), List.of()),
            tool("get_tennis_match",
                "One tennis match's detail: players, surface, win probabilities, total-games and "
                + "ace/double-fault markets. Needs a matchId from get_tennis_matches_today.",
                Map.of("matchId", strProp("The match's numeric id (as a string).")),
                List.of("matchId")),
            tool("get_model_accuracy",
                "How the projection model has performed lately: per-market Brier vs baseline and "
                + "calibration over a recent window.",
                Map.of("days", strProp("Look-back window in days, 7-180 (as a string). Default 30.")),
                List.of()));
    }

    /** Short human label for the live "agent working" status feed. */
    public String label(String toolName) {
        return switch (toolName) {
            case "get_today_games" -> "Checking tonight's MLB slate…";
            case "get_game_projections" -> "Reading the game's batter projections…";
            case "get_best_plays" -> "Scanning the best-EV board…";
            case "get_prop_board" -> "Looking at the model's prop picks…";
            case "get_most_likely" -> "Running the game-simulator board…";
            case "search_player" -> "Finding the player…";
            case "get_player" -> "Pulling the player's recent form…";
            case "get_tennis_matches_today" -> "Checking today's tennis slate…";
            case "get_tennis_match" -> "Reading the match detail…";
            case "get_model_accuracy" -> "Checking how the model's been doing…";
            default -> "Looking that up…";
        };
    }

    // ── Navigable links ──────────────────────────────────────────────────────────

    /**
     * Map a tool call to an in-app deep link (the "go to the relevant page" result), grounded in
     * the ids the model actually used and labelled from the tool's own result where easy. Returns
     * empty when the tool has no natural page (or a required id is missing).
     */
    public Optional<LinkRef> linkFor(String toolName, Map<String, Object> args, String resultJson) {
        JsonNode result = parse(resultJson);
        return switch (toolName) {
            case "get_player" -> {
                String id = optStr(args, "playerId");
                if (id == null) {
                    yield Optional.empty();
                }
                String name = result == null ? null : text(result.path("player").path("fullName"));
                yield Optional.of(new LinkRef(name != null ? name : "Player page", "/mlb/players/" + id));
            }
            case "search_player" -> {
                if (result != null && result.isArray() && !result.isEmpty()) {
                    JsonNode top = result.get(0);
                    String id = text(top.path("id"));
                    String name = text(top.path("fullName"));
                    if (id != null) {
                        yield Optional.of(new LinkRef(name != null ? name : "Player page", "/mlb/players/" + id));
                    }
                }
                yield Optional.empty();
            }
            case "get_game_projections" -> idLink(args, "gameId", "Game projections", "/mlb/games/");
            case "get_tennis_match" -> idLink(args, "matchId", "Match detail", "/tennis/matches/");
            case "get_best_plays" -> Optional.of(new LinkRef("Best Lines", "/mlb/odds"));
            case "get_most_likely" -> Optional.of(new LinkRef("Most Likely board", "/mlb/most-likely"));
            case "get_prop_board", "get_today_games" -> Optional.of(new LinkRef("Today's Board", "/"));
            case "get_model_accuracy" -> Optional.of(new LinkRef("Model accuracy", "/mlb/accuracy"));
            case "get_tennis_matches_today" -> Optional.of(new LinkRef("Tennis matches", "/tennis/matches"));
            default -> Optional.empty();
        };
    }

    private static Optional<LinkRef> idLink(Map<String, Object> args, String key, String label, String prefix) {
        String id = optStr(args, key);
        return id == null ? Optional.empty() : Optional.of(new LinkRef(label, prefix + id));
    }

    private JsonNode parse(String json) {
        if (json == null) {
            return null;
        }
        try {
            return mapper.readTree(json);
        } catch (Exception e) {
            return null;
        }
    }

    /** JsonNode text or null for missing/null nodes (asText would return "" / "null"). */
    private static String text(JsonNode node) {
        return node == null || node.isMissingNode() || node.isNull() ? null : node.asText();
    }

    // ── Dispatch ────────────────────────────────────────────────────────────────

    /** Execute a tool by name against the live services; always returns JSON (errors included). */
    public String execute(String name, Map<String, Object> args) {
        try {
            return switch (name) {
                case "get_today_games" -> json(games.todayGames(LocalDate.now()));
                case "get_game_projections" -> json(projections.gameProjections(reqLong(args, "gameId")));
                case "get_best_plays" -> json(cap(odds.bestPlays(date(args)), BEST_PLAYS_CAP));
                case "get_prop_board" -> json(propBoard.board(date(args)));
                case "get_most_likely" -> json(mostLikely.board(date(args)));
                case "search_player" -> json(players.searchByName(reqStr(args, "name"), PLAYER_SEARCH_CAP));
                case "get_player" -> json(player(reqInt(args, "playerId")));
                case "get_tennis_matches_today" -> json(tennis.scheduledMatches());
                case "get_tennis_match" -> json(tennis.matchDetail(reqLong(args, "matchId")));
                case "get_model_accuracy" -> json(accuracy.accuracy(days(args)));
                default -> error("unknown tool: " + name);
            };
        } catch (IllegalArgumentException e) {
            return error(e.getMessage());
        } catch (Exception e) {
            return error("tool '" + name + "' failed: " + e.getMessage());
        }
    }

    private Map<String, Object> player(int playerId) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("player", players.findById(playerId).orElse(null));
        out.put("recent", players.findRecent(playerId, PLAYER_RECENT_GAMES));
        return out;
    }

    // ── Helpers ──────────────────────────────────────────────────────────────────

    private static <T> List<T> cap(List<T> list, int n) {
        return list.size() <= n ? list : list.subList(0, n);
    }

    private String json(Object o) {
        try {
            return mapper.writeValueAsString(o);
        } catch (Exception e) {
            return error("serialization failed");
        }
    }

    private static String error(String message) {
        return "{\"error\":" + quote(message) + "}";
    }

    private static String quote(String s) {
        return "\"" + (s == null ? "" : s.replace("\\", "\\\\").replace("\"", "\\\"")) + "\"";
    }

    private static LocalDate date(Map<String, Object> in) {
        String s = optStr(in, "date");
        return (s == null || s.isBlank()) ? LocalDate.now() : LocalDate.parse(s.trim());
    }

    private static int days(Map<String, Object> in) {
        String s = optStr(in, "days");
        int d = (s == null || s.isBlank()) ? 30 : Integer.parseInt(s.trim());
        return Math.min(Math.max(d, 7), 180);
    }

    /** Tool arg as a string, tolerant of the model returning a number instead of a string. */
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

    private static String reqStr(Map<String, Object> in, String key) {
        String s = optStr(in, key);
        if (s == null || s.isBlank()) {
            throw new IllegalArgumentException("missing required parameter '" + key + "'");
        }
        return s.trim();
    }

    private static long reqLong(Map<String, Object> in, String key) {
        try {
            return Long.parseLong(reqStr(in, key));
        } catch (NumberFormatException e) {
            throw new IllegalArgumentException("parameter '" + key + "' must be a number");
        }
    }

    private static int reqInt(Map<String, Object> in, String key) {
        return Math.toIntExact(reqLong(in, key));
    }

    private static FunctionDeclaration tool(String name, String description,
                                            Map<String, Schema> properties, List<String> required) {
        Schema params = Schema.builder()
            .type("OBJECT")
            .properties(properties)
            .required(required.toArray(new String[0]))
            .build();
        return FunctionDeclaration.builder()
            .name(name)
            .description(description)
            .parameters(params)
            .build();
    }

    private static Schema strProp(String description) {
        return Schema.builder().type("STRING").description(description).build();
    }
}
