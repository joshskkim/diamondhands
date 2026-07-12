package com.diamond.api.service;

import com.diamond.api.dto.*;
import com.diamond.api.repository.ClearRateRepository;
import com.diamond.api.repository.ClearRateRepository.ClearRates;
import com.diamond.api.repository.OddsRepository;
import com.diamond.api.repository.OddsRepository.GameMeta;
import com.diamond.api.repository.OddsRepository.GameOddRow;
import com.diamond.api.repository.OddsRepository.PropOddRow;
import com.diamond.api.repository.OddsRepository.RunProj;
import io.micrometer.observation.annotation.Observed;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Turns stored odds into (a) per-game best lines with model edge and (b) a slate-wide
 * "best plays" board. Best line = highest decimal price across books for a side/line.
 * Model edge (EV%) is attached where we have a model probability: moneyline/run_line/total
 * via {@link OddsModel} on projected runs, and every player-prop market the odds feed
 * carries via {@link #propOverProb} — as long as the book's line is one the model can
 * price. Batter probabilities are then regressed toward the player's demonstrated clear
 * rate ({@link PropBlend}) so a number here matches the prop board's for the same
 * selection.
 */
@Service
public class OddsService {

    private static final List<String> GAME_MARKET_ORDER = List.of("moneyline", "run_line", "total");

    // A model probability of (effectively) 0 or 1 is not a confident edge — it's the
    // "not really projected" sentinel. A batter with expected_pa = 0 (no confirmed lineup
    // slot) gives p_hit_1plus = 0, and a 0-run game projection gives pTotalOver = 0; either
    // way the *opposite* side reads as a phantom 100% and floats to the top of the board
    // (the under-at-100% bug). Real projections never land within EPS of 0/1, so we drop
    // such degenerate probabilities to null (no EV, no edge, no model% shown).
    private static final double PROB_EPS = 1e-6;

    private final OddsRepository repo;
    private final ClearRateRepository clearRates;

    public OddsService(OddsRepository repo, ClearRateRepository clearRates) {
        this.repo = repo;
        this.clearRates = clearRates;
    }

    @Cacheable(cacheNames = "odds", key = "#gameId")
    public GameOddsResponse gameOdds(long gameId) {
        List<GameOddRow> gameRows = repo.findGameOdds(gameId);
        List<PropOddRow> propRows = repo.findPropOdds(gameId);
        if (gameRows.isEmpty() && propRows.isEmpty()) {
            return new GameOddsResponse(gameId, false, List.of(), List.of());
        }
        return buildGameOdds(gameId, gameRows, propRows, repo.findRunProj(gameId),
            clearRatesFor(propRows, repo.findGameDate(gameId)));
    }

    /** Clear rates for every player quoted in these props, in one query. */
    private Map<Integer, ClearRates> clearRatesFor(List<PropOddRow> propRows, LocalDate date) {
        if (date == null || propRows.isEmpty()) return Map.of();
        Set<Integer> ids = new HashSet<>();
        for (PropOddRow r : propRows) ids.add(r.playerId());
        return clearRates.findClearRatesBatch(ids, date);
    }

    /** Build a game's odds response from already-fetched rows (shared by the per-game and
     *  slate-batch paths). */
    private GameOddsResponse buildGameOdds(long gameId, List<GameOddRow> gameRows,
                                           List<PropOddRow> propRows, RunProj proj,
                                           Map<Integer, ClearRates> ratesByPlayer) {
        if (gameRows.isEmpty() && propRows.isEmpty()) {
            return new GameOddsResponse(gameId, false, List.of(), List.of());
        }
        OddsModel model = proj == null ? null : new OddsModel(proj.expHome(), proj.expAway());
        return new GameOddsResponse(gameId, true, buildGameMarkets(gameRows, model),
            buildProps(propRows, ratesByPlayer));
    }

    /** Batter prop over-prices for the slate (best price across books), keyed for Best Bets. */
    @Cacheable(cacheNames = "oddsProps", key = "#date")
    public List<BatterPropOddsDto> batterProps(LocalDate date) {
        List<BatterPropOddsDto> out = new ArrayList<>();
        for (OddsRepository.BatterPropRow r : repo.findBatterProps(date)) {
            out.add(new BatterPropOddsDto(
                r.gameId(), r.playerId(), r.market(), r.line(),
                r.bookmaker(), r.priceAmerican(), r.priceDecimal()));
        }
        return out;
    }

    /** Multi-book price ladder per prop selection (line shopping), best price first. */
    @Cacheable(cacheNames = "oddsLineShop", key = "#date")
    public List<LineShopDto> lineShop(LocalDate date) {
        // Rows arrive grouped by selection and best-decimal-first (see PROP_QUOTES_SQL).
        Map<String, List<BookQuoteDto>> byKey = new LinkedHashMap<>();
        for (OddsRepository.PropQuoteRow r : repo.findPropQuotes(date)) {
            String key = lineShopKey(r.gameId(), r.playerId(), r.market(), r.side(), r.line());
            byKey.computeIfAbsent(key, k -> new ArrayList<>())
                 .add(new BookQuoteDto(r.bookmaker(), r.priceAmerican(), r.priceDecimal()));
        }
        List<LineShopDto> out = new ArrayList<>(byKey.size());
        for (Map.Entry<String, List<BookQuoteDto>> e : byKey.entrySet()) {
            out.add(new LineShopDto(e.getKey(), e.getValue()));
        }
        return out;
    }

    /** Selection key shared with the client: line trailing-zeros stripped (0.50 → "0.5"). */
    static String lineShopKey(long gameId, int playerId, String market, String side, double line) {
        return gameId + ":" + playerId + ":" + market + ":" + side + ":" + PropDistribution.lineKey(line);
    }

    /** Hit-rate "traffic light" per batter prop market for the slate (last 5/10/20 + season). */
    @Cacheable(cacheNames = "oddsHitRates", key = "#date")
    public List<HitRateDto> hitRates(LocalDate date) {
        LocalDate seasonStart = LocalDate.of(date.getYear(), 1, 1);
        List<HitRateDto> out = new ArrayList<>();
        for (OddsRepository.HitRateRow r : repo.findHitRates(date, seasonStart)) {
            out.add(new HitRateDto(
                r.playerId(), r.market(), r.line(),
                r.l5(), r.l10(), r.l20(), r.n20(), r.season(), r.nSeason()));
        }
        return out;
    }

    @Observed(name = "odds.bestPlays", contextualName = "odds.bestPlays")
    @Cacheable(cacheNames = "oddsBest", key = "#date")
    public List<BestPlayDto> bestPlays(LocalDate date) {
        // Fetch the whole slate's odds/props/projections/meta in a handful of queries,
        // instead of ~five queries per game (the old per-game gameOdds() loop was an N+1
        // over the slate). Clear rates likewise: one batch for every quoted player.
        Map<Long, List<GameOddRow>> oddsByGame = repo.findGameOddsByDate(date);
        Map<Long, List<PropOddRow>> propsByGame = repo.findPropOddsByDate(date);
        Map<Long, RunProj> projByGame = repo.findRunProjByDate(date);
        Map<Long, GameMeta> metaByGame = repo.findGameMetaByDate(date);
        Map<String, OddsRepository.VerdictRow> verdicts = repo.findPickVerdictsByDate(date);
        Map<Integer, ClearRates> ratesByPlayer = clearRatesFor(
            propsByGame.values().stream().flatMap(List::stream).toList(), date);

        List<BestPlayDto> plays = new ArrayList<>();
        for (long gameId : repo.findGameIdsWithOdds(date)) {
            GameOddsResponse odds = buildGameOdds(gameId,
                oddsByGame.getOrDefault(gameId, List.of()),
                propsByGame.getOrDefault(gameId, List.of()),
                projByGame.get(gameId),
                ratesByPlayer);
            if (!odds.hasOdds()) continue;
            GameMeta meta = metaByGame.get(gameId);
            String matchup = meta == null ? "" : meta.awayAbbr() + " @ " + meta.homeAbbr();

            for (GameMarketDto market : odds.game()) {
                for (LineQuoteDto q : market.quotes()) {
                    addPlay(plays, verdicts, gameId, matchup, market.market(), q.side(),
                        gameSelection(market.market(), q.side(), q.line(), meta), q, null, null);
                }
            }
            for (PropMarketDto prop : odds.props()) {
                addPlay(plays, verdicts, gameId, matchup, prop.market(), "over",
                    propSelection(prop, "over"), prop.over(), prop.player().id(), prop.player().name());
                addPlay(plays, verdicts, gameId, matchup, prop.market(), "under",
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
                Double fairProb = OddsMath.fairShare(best.impliedProb(), impliedSum);
                quotes.add(new LineQuoteDto(
                    best.side(), best.line(), best.bookmaker(),
                    best.priceAmerican(), best.priceDecimal(), best.impliedProb(),
                    fairProb, modelProb, OddsMath.ev(modelProb, best.priceDecimal()), gameBooks(books)));
            }
            quotes.sort(SIDE_ORDER);
            out.add(new GameMarketDto(market, quotes));
        }
        return out;
    }

    private Double gameModelProb(OddsModel model, String market, String side, Double line) {
        if (model == null) return null;
        Double prob = switch (market) {
            case "moneyline" -> side.equals("home") ? model.pHomeWin() : 1.0 - model.pHomeWin();
            case "total" -> {
                double over = model.pTotalOver(line);
                yield side.equals("over") ? over : 1.0 - over;
            }
            case "run_line" -> side.equals("home") ? model.pHomeCover(line) : model.pAwayCover(line);
            default -> null;
        };
        return sane(prob);
    }

    // ── Player props ─────────────────────────────────────────────────────────

    private List<PropMarketDto> buildProps(List<PropOddRow> rows, Map<Integer, ClearRates> ratesByPlayer) {
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
            // sane() drops a degenerate p (e.g. p_hit_1plus = 0 for a 0-PA batter); without
            // it the under reads 1.0 - 0 = 100%. It MUST run on the raw probability: 0/1 is
            // the "not really projected" sentinel, and blending a 0.0 toward the league rate
            // would launder it into a plausible-looking ~0.18 that sails past the guard.
            Double rawProb = sane(propOverProb(any.market(), any.line(), any.model()));
            // Then regress toward the batter's demonstrated clear rate, so a player reads the
            // same here as on the prop board. PropBlend no-ops for markets/lines with no
            // comparable rate (every pitcher market, and off-canonical lines like hit 1.5).
            // A convex blend of a sane p with a league rate stays inside (0, 1).
            Double overProb = rawProb == null ? null : PropBlend.blend(
                any.market(), any.line(), rawProb, ratesByPlayer.get(any.playerId()));
            Double underProb = overProb == null ? null : 1.0 - overProb;
            List<PropOddRow> overBooks = sides.get("over");
            List<PropOddRow> underBooks = sides.get("under");
            // De-vig over/under only when both sides are quoted (independent of the model,
            // so even unmodeled pitcher props get a fair line for display).
            Double fairOver = null, fairUnder = null;
            if (overBooks != null && !overBooks.isEmpty() && underBooks != null && !underBooks.isEmpty()) {
                double sum = overBooks.get(0).impliedProb() + underBooks.get(0).impliedProb();
                fairOver = OddsMath.fairShare(overBooks.get(0).impliedProb(), sum);
                fairUnder = OddsMath.fairShare(underBooks.get(0).impliedProb(), sum);
            }
            LineQuoteDto over = propQuote(overBooks, overProb, fairOver);
            LineQuoteDto under = propQuote(underBooks, underProb, fairUnder);
            out.add(new PropMarketDto(player, any.market(), any.line(), over, under));
        }
        return out;
    }

    /**
     * Over probability for a prop line from our model, or null when we can't price this
     * market at this line. Two families:
     *
     * <ul>
     *   <li>Occurrence props (hit/hr/bb) are closed-form per-PA probabilities computed at
     *       one fixed line each — a book quoting hit 2.5 gets no model.</li>
     *   <li>Line-based props read P(over) off a stored distribution: the simulator's
     *       histograms (tb/hrr, hits-allowed/ER) price any half-line, while the workload
     *       model's K/outs ladders only hold the lines projection/workload.py materialized.</li>
     * </ul>
     *
     * <p>hit at 0.5 reads the engine's SERVED prob ({@code p_hit_1plus_served}) — already
     * clear-rate blended, so {@link PropBlend} no longer blends hit (see its CANONICAL map).
     * hit 1.5 still uses the raw {@code p_hit_2plus}. Null served = degenerate raw the engine
     * declined to blend → no play, same as any unpriced line.
     */
    private Double propOverProb(String market, double line, OddsRepository.PropModelRow m) {
        if (m == null) return null;
        return switch (market) {
            case "hit" -> line == 0.5 ? m.pHit1Served() : line == 1.5 ? m.pHit2() : null;
            case "hr" -> line == 0.5 ? m.pHr() : null;
            case "bb" -> line == 0.5 ? m.pBb1() : null;
            case "tb" -> PropDistribution.histProb(m.tbHist(), m.simNSims(), line);
            case "hrr" -> PropDistribution.histProb(m.hrrHist(), m.simNSims(), line);
            case "pitcher_k" -> PropDistribution.ladderProb(m.pK(), line);
            case "pitcher_outs" -> PropDistribution.ladderProb(m.pOuts(), line);
            case "pitcher_hits_allowed" ->
                PropDistribution.histProb(m.hitsHist(), m.pitcherNSims(), line);
            case "pitcher_earned_runs" ->
                PropDistribution.histProb(m.erHist(), m.pitcherNSims(), line);
            default -> null;
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
            fairProb, modelProb, OddsMath.ev(modelProb, best.priceDecimal()), all);
    }

    // ── Shared helpers ─────────────────────────────────────────────────────────

    /** A model probability is usable only if it's strictly inside (0, 1); 0/1 means the
     *  projection is degenerate (not really projected), not a confident edge. See PROB_EPS. */
    private static Double sane(Double p) {
        return (p == null || p <= PROB_EPS || p >= 1.0 - PROB_EPS) ? null : p;
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

    private void addPlay(List<BestPlayDto> plays, Map<String, OddsRepository.VerdictRow> verdicts,
                         long gameId, String matchup, String market,
                         String side, String selection, LineQuoteDto q, Integer playerId, String playerName) {
        if (q == null || q.evPct() == null || q.modelProb() == null) return;
        OddsRepository.VerdictRow v = verdicts.get(OddsRepository.verdictKey(gameId, market, side, playerId));
        plays.add(new BestPlayDto(
            gameId, matchup, market, side, selection, q.line(), q.bestBook(),
            q.priceAmerican(), q.priceDecimal(), q.modelProb(), q.impliedProb(), q.fairProb(), q.evPct(),
            playerId, playerName,
            v == null ? null : v.verdict(), v == null ? null : v.confidence(),
            v == null ? null : v.rationale()));
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
            case "bb" -> "Walks";
            case "tb" -> "Total bases";
            case "hrr" -> "H+R+RBI";
            case "pitcher_k" -> "Ks";
            case "pitcher_outs" -> "Outs";
            case "pitcher_hits_allowed" -> "Hits allowed";
            case "pitcher_earned_runs" -> "Earned runs";
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
