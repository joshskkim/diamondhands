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
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.function.Function;

/**
 * Builds the model-first prop board: for each batter prop market, the single most
 * likely player on the slate by the mechanistic model's own probability. Deliberately
 * independent of sportsbook odds — when a cached over-price exists it's attached as
 * context (with EV at that price), but the board renders the same without it.
 */
@Service
public class PropBoardService {

    /** A market definition: model probability + the weather adjustment that drives it. */
    private record Market(String key, String oddsMarket,
                          Function<SlateRow, Double> prob,
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
        new Market("hit", "hit", SlateRow::pHit1, SlateRow::adjWeatherHits, 0.45, 0.62),
        new Market("hr",  "hr",  SlateRow::pHr,   SlateRow::adjWeatherHr,   0.08, 0.15),
        new Market("k",   null,  SlateRow::pK1,   r -> null,                null, 0.66));

    private final PropBoardRepository repo;

    public PropBoardService(PropBoardRepository repo) {
        this.repo = repo;
    }

    /** A candidate scored for one market: its clear rates and blended probability. */
    private record Scored(SlateRow row, ClearRates rates, double blended) {}

    @Cacheable(cacheNames = "propBoard", key = "#date.toString()")
    public PropBoardResponse board(LocalDate date) {
        List<SlateRow> rows = repo.findSlateRows(date);
        List<PropBoardPickDto> picks = new ArrayList<>();
        // One player at most once across the TOP picks — three cards of the same
        // batter is a worse display than the marginally-less-likely runner-up.
        Set<Integer> used = new HashSet<>();

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
                    ClearRates rates = repo.findClearRates(r.playerId(), date);
                    return new Scored(r, rates,
                        blend(m.prob().apply(r), seasonRate(m.key(), rates),
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
        Function<PitcherRow, List<Double>> probs) {} // P(over each line), aligned to lines

    private static final List<PitcherMarket> PITCHER_MARKETS = List.of(
        new PitcherMarket("pitcher_k", PitcherRow::expectedK, List.of(4.5, 5.5, 6.5),
            r -> List.of(nz(r.pk45()), nz(r.pk55()), nz(r.pk65()))),
        new PitcherMarket("pitcher_outs", PitcherRow::expectedOuts, List.of(14.5, 17.5),
            r -> List.of(nz(r.po145()), nz(r.po175()))));

    private List<PitcherPropPickDto> pitcherPicks(LocalDate date) {
        List<PitcherRow> rows = repo.findPitcherRows(date);
        List<PitcherPropPickDto> out = new ArrayList<>();
        for (PitcherMarket m : PITCHER_MARKETS) {
            List<PitcherRow> ranked = rows.stream()
                .filter(r -> m.volume().apply(r) != null)
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
        List<Double> probs = m.probs().apply(top);
        List<PitcherPropPickDto.Threshold> dist = new ArrayList<>();
        for (int i = 0; i < lines.size(); i++) {
            dist.add(new PitcherPropPickDto.Threshold(lines.get(i), round(probs.get(i), 4)));
        }

        PitcherPrice price = repo.findPitcherOverPrice(top.gameId(), top.pitcherId(), m.key());
        // EV only when the book line matches a modeled threshold (so we have P(over)).
        Double evPct = null;
        if (price != null && price.line() != null) {
            int idx = lines.indexOf(price.line());
            if (idx >= 0) {
                evPct = round(probs.get(idx) * price.priceDecimal() - 1.0, 4);
            }
        }

        List<PitcherPropPickDto.RunnerUp> runnersUp = next.stream()
            .map(r -> new PitcherPropPickDto.RunnerUp(
                r.pitcherId(), r.pitcher(), r.team(), round(m.volume().apply(r), 2)))
            .toList();

        return new PitcherPropPickDto(
            m.key(), top.gameId(), top.matchup(), top.pitcherId(), top.pitcher(),
            top.team(), top.opponent(),
            round(m.volume().apply(top), 2), round(top.expectedIp(), 2),
            dist,
            price == null ? null : price.line(),
            price == null ? null : price.bookmaker(),
            price == null ? null : price.priceAmerican(),
            evPct,
            runnersUp);
    }

    private static double nz(Double v) {
        return v == null ? 0.0 : v;
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
            r.stadium(),
            r.bats(), r.pullPct(), r.fbPct(), r.avgLaunchSpeed(),
            pullFence, pullWall,
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
