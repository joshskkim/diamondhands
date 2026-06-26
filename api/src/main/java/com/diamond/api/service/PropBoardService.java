package com.diamond.api.service;

import com.diamond.api.dto.PitcherPropPickDto;
import com.diamond.api.dto.PropBoardPickDto;
import com.diamond.api.dto.PropBoardResponse;
import com.diamond.api.repository.PropBoardRepository;
import com.diamond.api.repository.PropBoardRepository.BestPrice;
import com.diamond.api.repository.PropBoardRepository.ClearRates;
import com.diamond.api.repository.PropBoardRepository.PitcherPrice;
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
import java.util.function.Function;
import java.util.function.Predicate;

/**
 * Builds the model-first prop board: for each batter prop market, the single most
 * likely player on the slate by the mechanistic model's own probability. Deliberately
 * independent of sportsbook odds — when a cached over-price exists it's attached as
 * context (with EV at that price), but the board renders the same without it.
 */
@Service
public class PropBoardService {

    /** A market definition: model probability + the weather adjustment that drives it.
     *  {@code simProb} is the Monte-Carlo simulator's estimate of the same market, blended
     *  into the closed-form model probability when sim-blending is enabled. */
    private record Market(String key, String oddsMarket,
                          Function<SlateRow, Double> prob,
                          Function<SlateRow, Double> simProb,
                          Function<SlateRow, Double> weather,
                          Double minSeasonRate,
                          double leagueRate) {}

    // Empirical-rate shrinkage (Jun 2026): the multiplicative adjustment chain
    // (park × pitcher × weather) can stack a league-average bat to the rate clamp —
    // the board once advertised an 85% hit prob for a player whose own season
    // clear-rate was 46%. Two-stage blend:
    //   1. the player's season clear-rate is regressed toward the LEAGUE clear-rate
    //      by sample size (PRIOR_N phantom games) — so a 5-game sample can't dodge
    //      scrutiny the way a raw n/(n+K) weight would allow;
    //   2. the model's probability is blended toward that stabilized empirical
    //      target, with the empirical side's weight growing with evidence.
    // The model still moves the number (that's its job); it just can't double a
    // 63-game track record or ride a 5-game rookie sample to the top of the board.
    private static final int SHRINK_K = 60;
    private static final int PRIOR_N = 25;
    // Per-market sanity floor for an over card (applied at n >= GUARD_MIN_N): a hit
    // pick needs a non-red season clear-rate; an HR pick needs a player who homers
    // in at least 8% of games. Thresholds are market-specific — hit-market bands
    // applied to HR would veto every slugger alive.
    private static final int GUARD_MIN_N = 15;
    private static final int CANDIDATE_POOL = 10;

    // Batter K has no odds-market counterpart in our data (books we ingest don't
    // quote it), so its price fields are always null.
    // League clear-rates per market (≈2025-26: share of starter games with 1+ hit /
    // 1+ HR / 1+ K) — the prior a thin empirical sample regresses toward.
    private static final List<Market> MARKETS = List.of(
        new Market("hit", "hit", SlateRow::pHit1, SlateRow::pSimHit, SlateRow::adjWeatherHits, 0.45, 0.62),
        new Market("hr",  "hr",  SlateRow::pHr,   SlateRow::pSimHr,  SlateRow::adjWeatherHr,   0.08, 0.15),
        new Market("k",   null,  SlateRow::pK1,   SlateRow::pSimK,   r -> null,                null, 0.66),
        // Walks (v2.11): no Monte-Carlo prop and no park/weather term. oddsMarket="bb" so a
        // best over-price attaches IF a book quotes batter walks (rare in our feed); the card
        // stands on the projection alone otherwise. leagueRate ≈ P(>=1 BB per game).
        new Market("bb",  "bb",  SlateRow::pBb1,  r -> null,         r -> null,                null, 0.30));

    // Sim-blend (Jun 2026): blend the Monte-Carlo simulator's per-batter prop estimate
    // into the closed-form binomial BEFORE the empirical shrinkage. The sim captures
    // lineup turnover and PA-count variance the closed-form model can't. OFF by default
    // and the per-market weights default to 0 — they are to be fit on the backtest harness
    // before anything ships live (env: DIAMOND_SIM_PROP_BLEND_ENABLED / _WEIGHT_HIT/_HR/_K).
    @Value("${diamond.sim-prop-blend.enabled:false}")
    private boolean simBlendEnabled;
    @Value("${diamond.sim-prop-blend.weight-hit:0.0}")
    private double simWeightHit;
    @Value("${diamond.sim-prop-blend.weight-hr:0.0}")
    private double simWeightHr;
    @Value("${diamond.sim-prop-blend.weight-k:0.0}")
    private double simWeightK;

    private final PropBoardRepository repo;

    public PropBoardService(PropBoardRepository repo) {
        this.repo = repo;
    }

    /** The configured sim-blend weight for a market (0 when unset → closed-form only). */
    private double simWeight(String key) {
        return switch (key) {
            case "hit" -> simWeightHit;
            case "hr"  -> simWeightHr;
            case "k"   -> simWeightK;
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
        Map<Integer, ClearRates> ratesByPlayer = repo.findClearRatesBatch(
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
                        blend(effectiveModelProb(m, r), seasonRate(m.key(), rates),
                              nSeasonOf(rates), m.leagueRate()));
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
    // Ranked by EXPECTED VOLUME (expected Ks / outs), not P(clear): pitcher lines
    // vary by arm, so "most likely to clear his line" would surface soft-tossers with
    // low lines, not the aces. One card per market; the distribution is the reasoning.

    private record PitcherMarket(
        String key,                                  // odds market key
        Function<PitcherRow, Double> volume,         // ranking metric
        List<Double> lines,                          // distribution thresholds shown
        Function<PitcherRow, List<Double>> probs,    // P(over each line), aligned to lines
        Predicate<PitcherRow> hasDist) {}            // true when the row carries a real distribution

    private static final List<Double> HITS_LINES = List.of(4.5, 5.5, 6.5);
    private static final List<Double> ER_LINES = List.of(1.5, 2.5, 3.5);

    private static final List<PitcherMarket> PITCHER_MARKETS = List.of(
        // K / outs distributions come from the workload model's JSON. When it's absent (no
        // pitcher_starts history → workload never computed), the cols are null; hasDist gates
        // those rows out so a missing projection isn't rendered as a confident 100% under.
        new PitcherMarket("pitcher_k", PitcherRow::expectedK, List.of(4.5, 5.5, 6.5),
            r -> List.of(nz(r.pk45()), nz(r.pk55()), nz(r.pk65())),
            r -> r.pk45() != null && r.pk55() != null && r.pk65() != null),
        new PitcherMarket("pitcher_outs", PitcherRow::expectedOuts, List.of(14.5, 17.5),
            r -> List.of(nz(r.po145()), nz(r.po175())),
            r -> r.po145() != null && r.po175() != null),
        // Hits allowed / earned runs come from the simulator's histograms, so P(over) is
        // read off the distribution rather than a closed form. Like Ks/outs, ranked by
        // expected volume — here that surfaces the starter most exposed to a big line
        // (the over lean), not the stingiest arm. No histogram (no sim row) → no card.
        new PitcherMarket("pitcher_hits_allowed", PitcherRow::expectedHits, HITS_LINES,
            r -> histPOver(r.hitsHist(), r.nSims(), HITS_LINES), r -> hasHist(r.hitsHist(), r.nSims())),
        new PitcherMarket("pitcher_earned_runs", PitcherRow::expectedEr, ER_LINES,
            r -> histPOver(r.erHist(), r.nSims(), ER_LINES), r -> hasHist(r.erHist(), r.nSims())));

    private List<PitcherPropPickDto> pitcherPicks(LocalDate date) {
        List<PitcherRow> rows = repo.findPitcherRows(date);
        List<PitcherPropPickDto> out = new ArrayList<>();
        for (PitcherMarket m : PITCHER_MARKETS) {
            List<PitcherRow> ranked = rows.stream()
                .filter(r -> m.volume().apply(r) != null && m.hasDist().test(r))
                .sorted(Comparator.comparingDouble((PitcherRow r) -> m.volume().apply(r)).reversed())
                .toList();
            if (ranked.isEmpty()) continue;
            // A starter can legitimately top both Ks and outs (the workhorse ace) —
            // these are distinct stats, so we don't dedupe across the two cards.
            out.add(toPitcherPick(m, ranked.get(0), ranked.stream().skip(1).limit(2).toList()));
        }
        return out;
    }

    private PitcherPropPickDto toPitcherPick(PitcherMarket m, PitcherRow top, List<PitcherRow> next) {
        List<Double> lines = m.lines();
        List<Double> probs = m.probs().apply(top);   // P(over) aligned to lines
        List<PitcherPropPickDto.Threshold> dist = new ArrayList<>();
        for (int i = 0; i < lines.size(); i++) {
            dist.add(new PitcherPropPickDto.Threshold(lines.get(i), round(probs.get(i), 4)));
        }
        double expected = m.volume().apply(top);

        // Best cached price each side (over/under share lines at a book).
        PitcherPrice overPrice = repo.findPitcherPrice(top.gameId(), top.pitcherId(), m.key(), "over");
        PitcherPrice underPrice = repo.findPitcherPrice(top.gameId(), top.pitcherId(), m.key(), "under");
        Double bookConsensus = overPrice != null && overPrice.line() != null ? overPrice.line()
            : (underPrice != null ? underPrice.line() : null);

        // Anchor line = the book's consensus line when it matches a modeled threshold,
        // else the modeled line closest to the expected value (the meaningful line —
        // not the trivially-high lowest one). The recommended SIDE is the model's lean
        // there: over when P(over) ≥ 0.5, else under. bestProb is that side's probability.
        int anchorIdx = (bookConsensus != null && indexOfLine(lines, bookConsensus) >= 0)
            ? indexOfLine(lines, bookConsensus)
            : nearestLineIdx(lines, expected);
        double anchorLine = lines.get(anchorIdx);
        double pOver = probs.get(anchorIdx);
        String bestSide = pOver >= 0.5 ? "over" : "under";
        double bestProb = "over".equals(bestSide) ? pOver : 1.0 - pOver;

        // Price + EV for the RECOMMENDED side at the anchor line (context only).
        PitcherPrice chosen = "over".equals(bestSide) ? overPrice : underPrice;
        Double bookLine = null, evPct = null;
        String bestBook = null;
        Integer priceAmerican = null;
        if (chosen != null && chosen.line() != null && sameLine(chosen.line(), anchorLine)) {
            bookLine = chosen.line();
            bestBook = chosen.bookmaker();
            priceAmerican = chosen.priceAmerican();
            evPct = round(bestProb * chosen.priceDecimal() - 1.0, 4);
        }

        List<PitcherPropPickDto.RunnerUp> runnersUp = next.stream()
            .map(r -> new PitcherPropPickDto.RunnerUp(
                r.pitcherId(), r.pitcher(), r.team(), round(m.volume().apply(r), 2)))
            .toList();

        return new PitcherPropPickDto(
            m.key(), top.gameId(), top.matchup(), top.pitcherId(), top.pitcher(),
            top.team(), top.opponent(),
            round(expected, 2), round(top.expectedIp(), 2),
            dist,
            anchorLine, bestSide, round(bestProb, 4),
            bookLine, bestBook, priceAmerican, evPct,
            round(top.pitcherKRate(), 4), round(top.pitcherBbRate(), 4),
            round(top.pitcherXwobaAgainst(), 4), round(top.pitcherHrPerPa(), 4),
            round(top.opponentKRate(), 4), round(top.opponentXwoba(), 4),
            top.arsenal(),
            runnersUp);
    }

    private static boolean sameLine(double a, double b) {
        return Math.abs(a - b) < 1e-9;
    }

    /** Index of {@code target} in {@code lines}, or -1 (epsilon match for half-lines). */
    private static int indexOfLine(List<Double> lines, double target) {
        for (int i = 0; i < lines.size(); i++) {
            if (sameLine(lines.get(i), target)) return i;
        }
        return -1;
    }

    /** Index of the modeled line closest to {@code value} (ties → lower line). */
    private static int nearestLineIdx(List<Double> lines, double value) {
        int best = 0;
        double bestDist = Math.abs(lines.get(0) - value);
        for (int i = 1; i < lines.size(); i++) {
            double d = Math.abs(lines.get(i) - value);
            if (d < bestDist) {
                bestDist = d;
                best = i;
            }
        }
        return best;
    }

    private static double nz(Double v) {
        return v == null ? 0.0 : v;
    }

    /** True when a simulator histogram is usable (the game had a sim row). Mirrors the
     *  emptiness guard in {@link #histPOver}: without it the card would render all-0% (a
     *  bogus 100% under) instead of being suppressed. */
    private static boolean hasHist(int[] hist, Integer nSims) {
        return hist != null && hist.length > 0 && nSims != null && nSims > 0;
    }

    /** P(over each line) from a simulator count histogram (bin i = sims with exactly i,
     *  last bin a >=N catch-all). Empty list when the game had no sim row. */
    private static List<Double> histPOver(int[] hist, Integer nSims, List<Double> lines) {
        if (hist == null || hist.length == 0 || nSims == null || nSims <= 0) {
            return lines.stream().map(l -> (Double) 0.0).toList();
        }
        List<Double> out = new ArrayList<>(lines.size());
        for (double line : lines) {
            int over = 0;
            for (int i = 0; i < hist.length; i++) {
                if (i > line) over += hist[i];
            }
            out.add((double) over / nSims);
        }
        return out;
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

    /** Blend the model's probability toward a league-stabilized empirical clear rate. */
    static double blend(double modelProb, Double seasonRate, Integer nSeason, double leagueRate) {
        int n = (seasonRate == null || nSeason == null) ? 0 : Math.max(nSeason, 0);
        double season = seasonRate == null ? leagueRate : seasonRate;
        // Stage 1: stabilize the empirical rate (PRIOR_N phantom league games).
        double empirical = (n * season + PRIOR_N * leagueRate) / (n + PRIOR_N);
        // Stage 2: weight the empirical side by how much evidence backs it.
        double w = (n + PRIOR_N) / (double) (n + PRIOR_N + SHRINK_K);
        return w * empirical + (1.0 - w) * modelProb;
    }

    private static boolean guardVetoed(Market m, ClearRates rates) {
        if (m.minSeasonRate() == null || rates == null || rates.nSeason() < GUARD_MIN_N) {
            return false;
        }
        Double season = seasonRate(m.key(), rates);
        return season != null && season < m.minSeasonRate();
    }

    private static Integer nSeasonOf(ClearRates rates) {
        return rates == null ? null : rates.nSeason();
    }

    private PropBoardPickDto toPick(Market m, Scored top,
                                    List<PropBoardPickDto.RunnerUp> runnersUp,
                                    LocalDate date) {
        SlateRow r = top.row();
        ClearRates rates = top.rates();
        double rawProb = m.prob().apply(r);
        double prob = top.blended();
        BestPrice price = m.oddsMarket() == null
            ? null
            : repo.findBestOverPrice(date, r.playerId(), m.oddsMarket());

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
            m.key(), 0.5,
            r.gameId(), r.matchup(),
            r.playerId(), r.player(), r.team(),
            r.lineupPosition(), r.lineupConfirmed(), r.expectedPa(),
            round(prob, 4),
            round(rawProb, 4),
            r.opposingPitcherId(), r.opposingPitcher(), r.pitcherDataQuality(),
            r.matchupXwoba(), r.matchupQuality(),
            r.adjPark(), r.adjPitcher(), m.weather().apply(r),
            r.adjDefense(),
            r.stadium(),
            r.bats(), r.pullPct(), r.fbPct(), r.avgLaunchSpeed(),
            pullFence, pullWall,
            r.hrDistanceFt(),
            rateFor(m.key(), rates, true),
            rateFor(m.key(), rates, false),
            rates == null ? null : rates.nSeason(),
            price == null ? null : price.bookmaker(),
            price == null ? null : price.priceAmerican(),
            price == null ? null : price.priceDecimal(),
            // EV at the cached price uses the blended (displayed) probability.
            price == null ? null : round(prob * price.priceDecimal() - 1.0, 4),
            runnersUp);
    }

    private static Double seasonRate(String market, ClearRates rates) {
        return rateFor(market, rates, false);
    }

    private static Double rateFor(String market, ClearRates rates, boolean l10) {
        if (rates == null) return null;
        return switch (market) {
            case "hit" -> l10 ? rates.hitL10() : rates.hitSeason();
            case "hr"  -> l10 ? rates.hrL10()  : rates.hrSeason();
            case "k"   -> l10 ? rates.kL10()   : rates.kSeason();
            case "bb"  -> l10 ? rates.bbL10()  : rates.bbSeason();
            default -> null;
        };
    }

    private static double round(double v, int places) {
        double f = Math.pow(10, places);
        return Math.round(v * f) / f;
    }

    private static Double round(Double v, int places) {
        return v == null ? null : round((double) v, places);
    }
}
