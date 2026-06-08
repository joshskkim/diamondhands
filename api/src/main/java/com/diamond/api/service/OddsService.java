package com.diamond.api.service;

import com.diamond.api.dto.*;
import com.diamond.api.repository.OddsRepository;
import com.diamond.api.repository.OddsRepository.GameMeta;
import com.diamond.api.repository.OddsRepository.GameOddRow;
import com.diamond.api.repository.OddsRepository.PropOddRow;
import com.diamond.api.repository.OddsRepository.RunProj;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Turns stored odds into (a) per-game best lines with model edge and (b) a slate-wide
 * "best plays" board. Best line = highest decimal price across books for a side/line.
 * Model edge (EV%) is attached where we have a model probability: moneyline/run_line/total
 * via {@link OddsModel} on projected runs, and hit/HR props directly from batter projections.
 */
@Service
public class OddsService {

    private static final List<String> GAME_MARKET_ORDER = List.of("moneyline", "run_line", "total");

    private final OddsRepository repo;

    public OddsService(OddsRepository repo) {
        this.repo = repo;
    }

    @Cacheable(cacheNames = "odds", key = "#gameId")
    public GameOddsResponse gameOdds(long gameId) {
        List<GameOddRow> gameRows = repo.findGameOdds(gameId);
        List<PropOddRow> propRows = repo.findPropOdds(gameId);
        if (gameRows.isEmpty() && propRows.isEmpty()) {
            return new GameOddsResponse(gameId, false, List.of(), List.of());
        }
        RunProj proj = repo.findRunProj(gameId);
        OddsModel model = proj == null ? null : new OddsModel(proj.expHome(), proj.expAway());

        return new GameOddsResponse(gameId, true, buildGameMarkets(gameRows, model), buildProps(propRows));
    }

    @Cacheable(cacheNames = "oddsBest", key = "#date")
    public List<BestPlayDto> bestPlays(LocalDate date) {
        List<BestPlayDto> plays = new ArrayList<>();
        for (long gameId : repo.findGameIdsWithOdds(date)) {
            GameOddsResponse odds = gameOdds(gameId);
            if (!odds.hasOdds()) continue;
            GameMeta meta = repo.findGameMeta(gameId);
            String matchup = meta == null ? "" : meta.awayAbbr() + " @ " + meta.homeAbbr();

            for (GameMarketDto market : odds.game()) {
                for (LineQuoteDto q : market.quotes()) {
                    addPlay(plays, gameId, matchup, market.market(), q.side(),
                        gameSelection(market.market(), q.side(), q.line(), meta), q, null, null);
                }
            }
            for (PropMarketDto prop : odds.props()) {
                addPlay(plays, gameId, matchup, prop.market(), "over",
                    propSelection(prop, "over"), prop.over(), prop.player().id(), prop.player().name());
                addPlay(plays, gameId, matchup, prop.market(), "under",
                    propSelection(prop, "under"), prop.under(), prop.player().id(), prop.player().name());
            }
        }
        // Rank by model-vs-fair edge (de-vigged), not raw EV — see edge() for why.
        plays.sort(Comparator.comparingDouble(OddsService::edge).reversed());
        return plays;
    }

    // ── Game markets ─────────────────────────────────────────────────────────

    private List<GameMarketDto> buildGameMarkets(List<GameOddRow> rows, OddsModel model) {
        // market -> "side|line" -> books (rows pre-sorted best-decimal-first per market/side)
        Map<String, Map<String, List<GameOddRow>>> grouped = new LinkedHashMap<>();
        for (GameOddRow r : rows) {
            grouped.computeIfAbsent(r.market(), m -> new LinkedHashMap<>())
                   .computeIfAbsent(r.side() + "|" + r.line(), k -> new ArrayList<>())
                   .add(r);
        }
        List<GameMarketDto> out = new ArrayList<>();
        for (String market : GAME_MARKET_ORDER) {
            Map<String, List<GameOddRow>> sides = grouped.get(market);
            if (sides == null) continue;
            // No-vig only makes sense for a clean two-way market; sum the two best implieds.
            Double impliedSum = sides.size() == 2
                ? sides.values().stream().mapToDouble(b -> b.get(0).impliedProb()).sum()
                : null;
            List<LineQuoteDto> quotes = new ArrayList<>();
            for (List<GameOddRow> books : sides.values()) {
                GameOddRow best = books.get(0); // highest decimal
                Double modelProb = gameModelProb(model, market, best.side(), best.line());
                Double fairProb = fairShare(best.impliedProb(), impliedSum);
                quotes.add(new LineQuoteDto(
                    best.side(), best.line(), best.bookmaker(),
                    best.priceAmerican(), best.priceDecimal(), best.impliedProb(),
                    fairProb, modelProb, ev(modelProb, best.priceDecimal()), gameBooks(books)));
            }
            quotes.sort(SIDE_ORDER);
            out.add(new GameMarketDto(market, quotes));
        }
        return out;
    }

    private Double gameModelProb(OddsModel model, String market, String side, Double line) {
        if (model == null) return null;
        return switch (market) {
            case "moneyline" -> side.equals("home") ? model.pHomeWin() : 1.0 - model.pHomeWin();
            case "total" -> {
                double over = model.pTotalOver(line);
                yield side.equals("over") ? over : 1.0 - over;
            }
            case "run_line" -> side.equals("home") ? model.pHomeCover(line) : model.pAwayCover(line);
            default -> null;
        };
    }

    // ── Player props ─────────────────────────────────────────────────────────

    private List<PropMarketDto> buildProps(List<PropOddRow> rows) {
        // (player|market|line) -> side -> books
        Map<String, Map<String, List<PropOddRow>>> grouped = new LinkedHashMap<>();
        for (PropOddRow r : rows) {
            grouped.computeIfAbsent(r.playerId() + "|" + r.market() + "|" + r.line(), k -> new LinkedHashMap<>())
                   .computeIfAbsent(r.side(), s -> new ArrayList<>())
                   .add(r);
        }
        List<PropMarketDto> out = new ArrayList<>();
        for (Map<String, List<PropOddRow>> sides : grouped.values()) {
            PropOddRow any = firstRow(sides);
            PlayerDto player = new PlayerDto(any.playerId(), any.playerName(), any.bats(), any.position());
            Double overProb = propOverProb(any.market(), any.line(), any);
            Double underProb = overProb == null ? null : 1.0 - overProb;
            List<PropOddRow> overBooks = sides.get("over");
            List<PropOddRow> underBooks = sides.get("under");
            // De-vig over/under only when both sides are quoted (independent of the model,
            // so even unmodeled pitcher props get a fair line for display).
            Double fairOver = null, fairUnder = null;
            if (overBooks != null && !overBooks.isEmpty() && underBooks != null && !underBooks.isEmpty()) {
                double sum = overBooks.get(0).impliedProb() + underBooks.get(0).impliedProb();
                fairOver = fairShare(overBooks.get(0).impliedProb(), sum);
                fairUnder = fairShare(underBooks.get(0).impliedProb(), sum);
            }
            LineQuoteDto over = propQuote(overBooks, overProb, fairOver);
            LineQuoteDto under = propQuote(underBooks, underProb, fairUnder);
            out.add(new PropMarketDto(player, any.market(), any.line(), over, under));
        }
        return out;
    }

    /** Over probability for a prop line from our model, or null for unmodeled markets. */
    private Double propOverProb(String market, double line, PropOddRow r) {
        return switch (market) {
            case "hit" -> line == 0.5 ? r.pHit1() : line == 1.5 ? r.pHit2() : null;
            case "hr" -> line == 0.5 ? r.pHr() : null;
            default -> null; // pitcher_k, pitcher_outs: best-line only for now
        };
    }

    private LineQuoteDto propQuote(List<PropOddRow> books, Double modelProb, Double fairProb) {
        if (books == null || books.isEmpty()) return null;
        PropOddRow best = books.get(0); // highest decimal
        List<BookPriceDto> all = new ArrayList<>();
        for (PropOddRow b : books) {
            all.add(new BookPriceDto(b.bookmaker(), b.priceAmerican(), b.priceDecimal(), b.impliedProb()));
        }
        return new LineQuoteDto(
            best.side(), best.line(), best.bookmaker(),
            best.priceAmerican(), best.priceDecimal(), best.impliedProb(),
            fairProb, modelProb, ev(modelProb, best.priceDecimal()), all);
    }

    // ── Shared helpers ─────────────────────────────────────────────────────────

    private static Double ev(Double modelProb, double decimal) {
        return modelProb == null ? null : modelProb * decimal - 1.0;
    }

    /** No-vig fair probability for one side: its implied divided by the two-sided implied sum. */
    private static Double fairShare(Double sideImplied, Double impliedSum) {
        if (sideImplied == null || impliedSum == null || impliedSum <= 0) return null;
        return sideImplied / impliedSum;
    }

    /**
     * Board ranking metric: how much our model disagrees with the no-vig market on this side.
     * Ranking by this instead of raw EV strips out the bookmaker's vig — which otherwise
     * systematically favored "under" on juiced markets like hit-Over-0.5. Falls back to raw
     * EV when the market couldn't be de-vigged (no opposite side quoted).
     */
    private static double edge(BestPlayDto p) {
        return p.fairProb() != null ? p.modelProb() - p.fairProb() : p.evPct();
    }

    private static List<BookPriceDto> gameBooks(List<GameOddRow> books) {
        List<BookPriceDto> out = new ArrayList<>();
        for (GameOddRow b : books) {
            out.add(new BookPriceDto(b.bookmaker(), b.priceAmerican(), b.priceDecimal(), b.impliedProb()));
        }
        return out;
    }

    private static PropOddRow firstRow(Map<String, List<PropOddRow>> sides) {
        for (List<PropOddRow> v : sides.values()) {
            if (!v.isEmpty()) return v.get(0);
        }
        throw new IllegalStateException("empty prop group");
    }

    /** home/over before away/under for stable display. */
    private static final Comparator<LineQuoteDto> SIDE_ORDER = Comparator.comparingInt(q ->
        switch (q.side()) {
            case "home", "over" -> 0;
            default -> 1;
        });

    private void addPlay(List<BestPlayDto> plays, long gameId, String matchup, String market,
                         String side, String selection, LineQuoteDto q, Integer playerId, String playerName) {
        if (q == null || q.evPct() == null || q.modelProb() == null) return;
        plays.add(new BestPlayDto(
            gameId, matchup, market, side, selection, q.line(), q.bestBook(),
            q.priceAmerican(), q.priceDecimal(), q.modelProb(), q.impliedProb(), q.fairProb(), q.evPct(),
            playerId, playerName));
    }

    private static String gameSelection(String market, String side, Double line, GameMeta meta) {
        String homeAbbr = meta == null ? "Home" : meta.homeAbbr();
        String awayAbbr = meta == null ? "Away" : meta.awayAbbr();
        return switch (market) {
            case "moneyline" -> (side.equals("home") ? homeAbbr : awayAbbr) + " ML";
            case "run_line" -> (side.equals("home") ? homeAbbr : awayAbbr) + " " + signed(line);
            case "total" -> (side.equals("over") ? "Over " : "Under ") + line;
            default -> market + " " + side;
        };
    }

    private static String propSelection(PropMarketDto prop, String side) {
        String label = switch (prop.market()) {
            case "hit" -> "Hit";
            case "hr" -> "HR";
            case "pitcher_k" -> "Ks";
            case "pitcher_outs" -> "Outs";
            default -> prop.market();
        };
        return prop.player().name() + " " + label + " "
            + (side.equals("over") ? "Over " : "Under ") + prop.line();
    }

    private static String signed(Double line) {
        if (line == null) return "";
        return line > 0 ? "+" + line : String.valueOf(line);
    }
}
