package com.diamond.api.service;

import com.diamond.api.dto.PitcherPropPickDto;
import com.diamond.api.dto.PropBoardPickDto;
import com.diamond.api.dto.PropBoardResponse;
import com.diamond.api.repository.PropBoardRepository;
import com.diamond.api.repository.PropBoardRepository.BestPrice;
import com.diamond.api.repository.ClearRateRepository;
import com.diamond.api.repository.ClearRateRepository.ClearRates;
import com.diamond.api.repository.PropBoardRepository.PitcherPrice;
import com.diamond.api.repository.PropBoardRepository.PitcherQuotes;
import com.diamond.api.repository.PropBoardRepository.PitcherRow;
import com.diamond.api.repository.PropBoardRepository.SlateRow;
import io.micrometer.observation.annotation.Observed;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.BiFunction;
import java.util.function.Function;
import java.util.function.Predicate;

import static com.diamond.api.service.PropDistribution.hasHist;
import static com.diamond.api.service.PropDistribution.histPOver;
import static com.diamond.api.service.PropDistribution.histProb;
import static com.diamond.api.service.PropDistribution.ladderProb;
import static com.diamond.api.service.PropDistribution.sameLine;

/**
 * Builds the prop board. BATTER cards stay model-first: for each market (H+R+RBI,
 * HR, total bases, walks) the single most likely player on the slate by the model's
 * own probability, deliberately independent of sportsbook odds — a cached price is
 * context (with EV), never the ranking. PITCHER cards are the opposite: ranked by
 * model-vs-line EDGE against the de-vigged book, and shown only when a beatable line
 * exists — see the pitcher section below.
 */
@Service
public class PropBoardService {

    /** A market definition: the card's line, model probability of clearing it, and the
     *  weather adjustment that drives it. {@code simProb} is the Monte-Carlo simulator's
     *  estimate of the same market, blended into the closed-form model probability when
     *  sim-blending is enabled (tb/hrr are sim-NATIVE — their prob already IS the sim). */
    private record Market(String key, String oddsMarket, double line,
                          Function<SlateRow, Double> prob,
                          Function<SlateRow, Double> simProb,
                          Function<SlateRow, Double> weather,
                          Double minSeasonRate) {}

    // Per-market sanity floor for an over card (applied at n >= GUARD_MIN_N): a hit
    // pick needs a non-red season clear-rate; an HR pick needs a player who homers
    // in at least 8% of games. Thresholds are market-specific — hit-market bands
    // applied to HR would veto every slugger alive.
    private static final int GUARD_MIN_N = 15;
    private static final int CANDIDATE_POOL = 10;

    // Each card's line must be the line PropBlend regresses toward — the clear rate is
    // measured at that line and nowhere else. tb/hrr replaced the old hit (1+ hit) and
    // K (1+ K) cards — those were low-signal occurrence props; these are real line-based
    // markets. Their model probability is the simulator's own distribution (P(over 1.5)
    // off the tb/hrr histograms), so batters without a sim row simply can't carry the
    // card, and there's no separate sim estimate to blend (simProb null, weight 0).
    private static final List<Market> MARKETS = List.of(
        new Market("hrr", "hrr", 1.5, r -> histProb(r.hrrHist(), r.simNSims(), 1.5),
            r -> null, SlateRow::adjWeatherHits, null),
        new Market("hr",  "hr",  0.5, SlateRow::pHr, SlateRow::pSimHr,
            SlateRow::adjWeatherHr, 0.08),
        new Market("tb",  "tb",  1.5, r -> histProb(r.tbHist(), r.simNSims(), 1.5),
            r -> null, SlateRow::adjWeatherHits, null),
        // Walks (v2.11): no Monte-Carlo prop and no park/weather term. oddsMarket="bb" so a
        // best over-price attaches IF a book quotes batter walks (rare in our feed); the card
        // stands on the projection alone otherwise.
        new Market("bb",  "bb",  0.5, SlateRow::pBb1, r -> null, r -> null, null));

    // Sim-blend (Jun 2026): blend the Monte-Carlo simulator's per-batter prop estimate
    // into the closed-form binomial BEFORE the empirical shrinkage. The sim captures
    // lineup turnover and PA-count variance the closed-form model can't. OFF by default
    // and the per-market weight defaults to 0 — to be fit on the backtest harness before
    // anything ships live (env: DIAMOND_SIM_PROP_BLEND_ENABLED / _WEIGHT_HR). Only HR
    // still has both a closed form and a sim estimate; tb/hrr are sim-native and the
    // hit/k cards (with their weights) were retired with the TB / H+R+RBI swap.
    @Value("${diamond.sim-prop-blend.enabled:false}")
    private boolean simBlendEnabled;
    @Value("${diamond.sim-prop-blend.weight-hr:0.0}")
    private double simWeightHr;

    private final PropBoardRepository repo;
    private final ClearRateRepository clearRates;

    public PropBoardService(PropBoardRepository repo, ClearRateRepository clearRates) {
        this.repo = repo;
        this.clearRates = clearRates;
    }

    /** The configured sim-blend weight for a market (0 when unset → closed-form only). */
    private double simWeight(String key) {
        return switch (key) {
            case "hr" -> simWeightHr;
            default -> 0.0;
        };
    }

    /** Closed-form model prob, optionally blended toward the simulator's estimate. Returns
     *  the closed-form value unchanged when blending is off, weight is 0, or the sim has no
     *  estimate for this batter (e.g. a padded lineup slot). */
    double effectiveModelProb(Market m, SlateRow r) {
        if (!simBlendEnabled) return m.prob().apply(r);
        return simBlend(m.prob().apply(r), m.simProb().apply(r), simWeight(m.key()));
    }

    /** Weighted blend of the closed-form model prob toward the simulator's estimate.
     *  No-op (returns the model prob unchanged) when the sim has no estimate or the
     *  weight is non-positive. */
    static double simBlend(double modelProb, Double simProb, double weight) {
        if (simProb == null || weight <= 0.0) return modelProb;
        return weight * simProb + (1.0 - weight) * modelProb;
    }

    /** A candidate scored for one market: its clear rates and blended probability. */
    private record Scored(SlateRow row, ClearRates rates, double blended) {}

    @Observed(name = "propboard.board", contextualName = "propBoard.board")
    @Cacheable(cacheNames = "propBoard", key = "#date.toString()")
    public PropBoardResponse board(LocalDate date) {
        List<SlateRow> rows = repo.findSlateRows(date);
        List<PropBoardPickDto> picks = new ArrayList<>();
        // One player at most once across the TOP picks — three cards of the same
        // batter is a worse display than the marginally-less-likely runner-up.
        Set<Integer> used = new HashSet<>();

        // Clear rates for every player that could enter any market's pool, fetched in ONE
        // query instead of per-candidate (was the dominant N+1 on this endpoint). Each
        // market re-ranks its top CANDIDATE_POOL by raw prob; `used` can drop up to
        // MARKETS-1 earlier picks, shifting at most that many deeper players into a later
        // pool — so prefetching that much extra depth is a guaranteed superset.
        Map<Integer, ClearRates> ratesByPlayer = clearRates.findClearRatesBatch(
            candidatePlayerIds(rows, CANDIDATE_POOL + MARKETS.size() - 1), date);

        for (Market m : MARKETS) {
            // Pool the strongest raw-model candidates, then re-rank by the shrunk
            // (model ⊕ demonstrated-rate) probability; top = card, next two =
            // honorable mentions.
            List<Scored> scored = rows.stream()
                .filter(r -> m.prob().apply(r) != null && r.expectedPa() != null)
                .filter(r -> !used.contains(r.playerId()))
                .sorted(Comparator.comparingDouble((SlateRow r) -> m.prob().apply(r)).reversed())
                .limit(CANDIDATE_POOL)
                .map(r -> {
                    ClearRates rates = ratesByPlayer.get(r.playerId());
                    return new Scored(r, rates,
                        PropBlend.blend(effectiveModelProb(m, r), PropBlend.seasonRate(m.key(), rates),
                              PropBlend.nSeason(m.key(), rates), PropBlend.leagueRate(m.key())));
                })
                .filter(s -> !guardVetoed(m, s.rates()))
                .sorted(Comparator.comparingDouble(Scored::blended).reversed())
                .toList();

            if (scored.isEmpty()) continue;
            Scored top = scored.get(0);
            used.add(top.row().playerId());
            List<PropBoardPickDto.RunnerUp> runnersUp = scored.stream()
                .skip(1).limit(2)
                .map(s -> new PropBoardPickDto.RunnerUp(
                    s.row().playerId(), s.row().player(), s.row().team(),
                    round(s.blended(), 4)))
                .toList();
            picks.add(toPick(m, top, runnersUp, date));
        }
        return new PropBoardResponse(
            date.toString(), rows.size(), picks, pitcherPicks(date));
    }

    // ── Pitcher props ───────────────────────────────────────────────────────────
    // Ranked by MODEL-VS-LINE EDGE, exactly like the game run-line/total: for every
    // priced starter, de-vig the book's over/under implied probabilities at his
    // consensus line and rank by |model P(over) − no-vig P(over)|; the recommended
    // side is wherever the edge points. A market with no starter carrying a beatable
    // two-way line (books not yet posted, or every quoted line outside the model's
    // range) simply produces no card — projection magnitude never selects a pick.

    private record PitcherMarket(
        String key,                                  // odds market key
        Function<PitcherRow, Double> volume,         // headline projection (expected K/outs/hits/ER)
        List<Double> lines,                          // distribution thresholds shown
        Function<PitcherRow, List<Double>> probs,    // P(over each line), aligned to lines
        Predicate<PitcherRow> hasDist,               // true when the row carries a real distribution
        // Model P(over) at an ARBITRARY book line — null when the model can't price it.
        // K/outs interpolate the workload ladder within its materialized range; hits/ER
        // hold the full sim histogram and can price any half-line.
        BiFunction<PitcherRow, Double, Double> probAtLine) {}

    private static final List<Double> K_LINES = List.of(4.5, 5.5, 6.5);
    private static final List<Double> OUTS_LINES = List.of(14.5, 17.5);
    private static final List<Double> HITS_LINES = List.of(4.5, 5.5, 6.5);
    private static final List<Double> ER_LINES = List.of(1.5, 2.5, 3.5);

    private static final List<PitcherMarket> PITCHER_MARKETS = List.of(
        // K / outs distributions come from the workload model's JSON ladders. When absent (no
        // pitcher_starts history → workload never computed), pK/pOuts are null; hasDist gates
        // those rows out so a missing projection isn't rendered as a confident 100% under.
        // probAtLine reads (and interpolates) the full ladder, so any book line in range prices
        // — the display distribution stays a fixed subset of thresholds for a stable card.
        new PitcherMarket("pitcher_k", PitcherRow::expectedK, K_LINES,
            r -> ladderProbs(r.pK(), K_LINES),
            r -> hasLadder(r.pK()),
            (r, line) -> ladderProb(r.pK(), line)),
        new PitcherMarket("pitcher_outs", PitcherRow::expectedOuts, OUTS_LINES,
            r -> ladderProbs(r.pOuts(), OUTS_LINES),
            r -> hasLadder(r.pOuts()),
            (r, line) -> ladderProb(r.pOuts(), line)),
        // Hits allowed / earned runs come from the simulator's histograms, so P(over) is
        // read off the distribution at any half-line. No histogram (no sim row) → no card.
        new PitcherMarket("pitcher_hits_allowed", PitcherRow::expectedHits, HITS_LINES,
            r -> histPOver(r.hitsHist(), r.nSims(), HITS_LINES),
            r -> hasHist(r.hitsHist(), r.nSims()),
            (r, line) -> histProb(r.hitsHist(), r.nSims(), line)),
        new PitcherMarket("pitcher_earned_runs", PitcherRow::expectedEr, ER_LINES,
            r -> histPOver(r.erHist(), r.nSims(), ER_LINES),
            r -> hasHist(r.erHist(), r.nSims()),
            (r, line) -> histProb(r.erHist(), r.nSims(), line)));

    /** A priced candidate: model vs de-vigged book at the consensus line. */
    private record Edged(PitcherRow row, PitcherQuotes quotes,
                         double modelPOver, double fairPOver) {
        String side() { return modelPOver >= fairPOver ? "over" : "under"; }
        double edge() { return Math.abs(modelPOver - fairPOver); }
    }

    private List<PitcherPropPickDto> pitcherPicks(LocalDate date) {
        List<PitcherRow> rows = repo.findPitcherRows(date);
        List<PitcherPropPickDto> out = new ArrayList<>();
        for (PitcherMarket m : PITCHER_MARKETS) {
            List<PitcherRow> eligible = rows.stream()
                .filter(r -> m.volume().apply(r) != null && m.hasDist().test(r))
                .toList();
            if (eligible.isEmpty()) continue;

            // Edge mode: every starter whose consensus line the model can price AND
            // whose both sides are quoted (two-way de-vig), ranked by |edge|.
            Map<PropBoardRepository.PitcherQuoteKey, PitcherQuotes> quotes =
                repo.findPitcherMarketQuotes(date, m.key());
            List<Edged> edged = eligible.stream()
                .map(r -> toEdged(m, r, quotes.get(
                    new PropBoardRepository.PitcherQuoteKey(r.gameId(), r.pitcherId()))))
                .filter(e -> e != null)
                .sorted(Comparator.comparingDouble(Edged::edge).reversed())
                .toList();

            // A card exists only when at least one starter has a beatable two-way line: the
            // pick is the biggest model-vs-line disparity, never raw projection magnitude. No
            // priceable line for the whole market (books not posted, lines off the model's
            // range) → no card, rather than a volume-ranked pick masquerading as an edge.
            if (edged.isEmpty()) continue;

            // Runners-up stay in edge order and carry their own side + edge — not a volume
            // leaderboard. A starter can legitimately top both Ks and outs (the workhorse
            // ace); these are distinct stats, so we don't dedupe across cards.
            List<PitcherPropPickDto.RunnerUp> runnersUp = edged.stream()
                .skip(1).limit(2)
                .map(e -> new PitcherPropPickDto.RunnerUp(
                    e.row().pitcherId(), e.row().pitcher(), e.row().team(),
                    round(m.volume().apply(e.row()), 2), e.side(), round(e.edge(), 4)))
                .toList();
            out.add(toPitcherPick(m, edged.get(0), runnersUp));
        }
        return out;
    }

    /** Model-vs-book comparison for one starter, or null when it can't be made: no quotes,
     *  one-sided quotes (no de-vig), or a book line the model has no distribution at. */
    private static Edged toEdged(PitcherMarket m, PitcherRow r, PitcherQuotes q) {
        if (q == null || q.overImplied() == null || q.underImplied() == null) return null;
        double sum = q.overImplied() + q.underImplied();
        if (sum <= 0) return null;
        Double modelPOver = m.probAtLine().apply(r, q.line());
        if (modelPOver == null) return null;
        return new Edged(r, q, modelPOver, q.overImplied() / sum);
    }

    /** Edge-mode card: anchored at the book's consensus line, side = where the edge
     *  points, price/EV from the best quote on that side. */
    private PitcherPropPickDto toPitcherPick(PitcherMarket m, Edged top,
                                             List<PitcherPropPickDto.RunnerUp> runnersUp) {
        PitcherRow row = top.row();
        double anchorLine = top.quotes().line();
        String bestSide = top.side();
        double bestProb = "over".equals(bestSide) ? top.modelPOver() : 1.0 - top.modelPOver();
        double fairProb = "over".equals(bestSide) ? top.fairPOver() : 1.0 - top.fairPOver();

        PitcherPrice chosen = "over".equals(bestSide) ? top.quotes().bestOver()
                                                      : top.quotes().bestUnder();
        Double bookLine = null, evPct = null;
        String bestBook = null;
        Integer priceAmerican = null;
        if (chosen != null) {
            bookLine = chosen.line();
            bestBook = chosen.bookmaker();
            priceAmerican = chosen.priceAmerican();
            evPct = round(bestProb * chosen.priceDecimal() - 1.0, 4);
        }
        return buildPitcherDto(m, row, anchorLine, bestSide, bestProb,
            bookLine, bestBook, priceAmerican, evPct,
            round(top.edge(), 4), round(fairProb, 4), "edge", runnersUp);
    }

    private PitcherPropPickDto buildPitcherDto(PitcherMarket m, PitcherRow top,
            double anchorLine, String bestSide, double bestProb,
            Double bookLine, String bestBook, Integer priceAmerican, Double evPct,
            Double edge, Double fairProb, String rankedBy,
            List<PitcherPropPickDto.RunnerUp> runnersUp) {
        List<Double> lines = m.lines();
        List<Double> probs = m.probs().apply(top);   // P(over) aligned to lines
        List<PitcherPropPickDto.Threshold> dist = new ArrayList<>();
        for (int i = 0; i < lines.size(); i++) {
            dist.add(new PitcherPropPickDto.Threshold(lines.get(i), round(probs.get(i), 4)));
        }
        return new PitcherPropPickDto(
            m.key(), top.gameId(), top.matchup(), top.pitcherId(), top.pitcher(),
            top.team(), top.opponent(),
            round(m.volume().apply(top), 2), round(top.expectedIp(), 2),
            dist,
            anchorLine, bestSide, round(bestProb, 4),
            bookLine, bestBook, priceAmerican, evPct,
            edge, fairProb, rankedBy,
            round(top.pitcherKRate(), 4), round(top.pitcherBbRate(), 4),
            round(top.pitcherXwobaAgainst(), 4), round(top.pitcherHrPerPa(), 4),
            round(top.opponentKRate(), 4), round(top.opponentXwoba(), 4),
            top.arsenal(),
            runnersUp);
    }

    private static double nz(Double v) {
        return v == null ? 0.0 : v;
    }

    /** True when a workload ladder is usable (the pitcher has a workload row). */
    private static boolean hasLadder(Map<String, Double> ladder) {
        return ladder != null && !ladder.isEmpty();
    }

    /** P(over) at each display line from a workload ladder (0.0 when off the grid) — the
     *  fixed distribution shown on the card, read from the same ladder that prices the edge. */
    private static List<Double> ladderProbs(Map<String, Double> ladder, List<Double> lines) {
        return lines.stream().map(l -> nz(ladderProb(ladder, l))).toList();
    }

    /** Union, across markets, of the top-{@code depth} players by raw model probability —
     *  the superset of players whose clear rates any market's pool could need. */
    private static Set<Integer> candidatePlayerIds(List<SlateRow> rows, int depth) {
        Set<Integer> ids = new HashSet<>();
        for (Market m : MARKETS) {
            rows.stream()
                .filter(r -> m.prob().apply(r) != null && r.expectedPa() != null)
                .sorted(Comparator.comparingDouble((SlateRow r) -> m.prob().apply(r)).reversed())
                .limit(depth)
                .forEach(r -> ids.add(r.playerId()));
        }
        return ids;
    }

    private static boolean guardVetoed(Market m, ClearRates rates) {
        if (m.minSeasonRate() == null || rates == null || rates.nSeason() < GUARD_MIN_N) {
            return false;
        }
        Double season = PropBlend.seasonRate(m.key(), rates);
        return season != null && season < m.minSeasonRate();
    }

    private PropBoardPickDto toPick(Market m, Scored top,
                                    List<PropBoardPickDto.RunnerUp> runnersUp,
                                    LocalDate date) {
        SlateRow r = top.row();
        ClearRates rates = top.rates();
        double rawProb = m.prob().apply(r);
        double prob = top.blended();
        // Price attach: 0.5 occurrence markets read the best cached over-price directly;
        // line-based markets (tb/hrr) find the book's consensus line and attach only when
        // it matches the modeled 1.5 anchor — prob/rates/EV all describe that line, so a
        // 2.5-quoted star simply shows no price rather than a mispriced EV.
        String bestBook = null;
        Integer priceAmerican = null;
        Double priceDecimal = null;
        if (m.oddsMarket() != null) {
            if (m.line() == 0.5) {
                BestPrice price = repo.findBestOverPrice(date, r.playerId(), m.oddsMarket());
                if (price != null) {
                    bestBook = price.bookmaker();
                    priceAmerican = price.priceAmerican();
                    priceDecimal = price.priceDecimal();
                }
            } else {
                PitcherPrice price = repo.findBatterLinePrice(date, r.playerId(), m.oddsMarket());
                if (price != null && price.line() != null && sameLine(price.line(), m.line())) {
                    bestBook = price.bookmaker();
                    priceAmerican = price.priceAmerican();
                    priceDecimal = price.priceDecimal();
                }
            }
        }

        // The fence this batter pulls toward: RHB → LF corner, LHB → RF. Switch
        // hitters have no single pull side, so the park-fit fields stay null.
        Double pullFence = null, pullWall = null;
        if ("R".equals(r.bats())) {
            pullFence = r.lfLineFt();
            pullWall = r.lfWallFt();
        } else if ("L".equals(r.bats())) {
            pullFence = r.rfLineFt();
            pullWall = r.rfWallFt();
        }

        return new PropBoardPickDto(
            m.key(), m.line(),
            r.gameId(), r.matchup(),
            r.playerId(), r.player(), r.team(),
            r.lineupPosition(), r.lineupConfirmed(), r.expectedPa(),
            round(prob, 4),
            round(rawProb, 4),
            r.opposingPitcherId(), r.opposingPitcher(), r.pitcherDataQuality(),
            round(r.oppPitcherBbRate(), 4), round(r.oppPitcherKRate(), 4),
            r.matchupXwoba(), r.matchupQuality(),
            r.adjPark(), r.adjPitcher(), m.weather().apply(r),
            r.adjDefense(),
            r.stadium(),
            r.bats(), r.pullPct(), r.fbPct(), r.avgLaunchSpeed(),
            pullFence, pullWall,
            r.hrDistanceFt(),
            PropBlend.rateFor(m.key(), rates, true),
            PropBlend.rateFor(m.key(), rates, false),
            PropBlend.nSeason(m.key(), rates),
            bestBook,
            priceAmerican,
            priceDecimal,
            // EV at the cached price uses the blended (displayed) probability.
            priceDecimal == null ? null : round(prob * priceDecimal - 1.0, 4),
            runnersUp);
    }

    private static double round(double v, int places) {
        double f = Math.pow(10, places);
        return Math.round(v * f) / f;
    }

    private static Double round(Double v, int places) {
        return v == null ? null : round((double) v, places);
    }
}
