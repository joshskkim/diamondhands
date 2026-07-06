package com.diamond.api.service;

import com.diamond.api.dto.EquityPointDto;
import com.diamond.api.dto.RecordSummaryDto;
import com.diamond.api.dto.TrackRecordResponse;
import com.diamond.api.repository.TrackRecordRepository;
import com.diamond.api.repository.TrackRecordRepository.SettledPick;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeSet;

/**
 * Aggregates settled Model's Picks into the live track record: overall / per-market / per-tier
 * record, units and ROI at flat 1-unit stakes, a per-day equity curve, and the picks' Brier.
 * See {@link TrackRecordResponse} for the (important) caveat on what pickBrier does and does not
 * measure.
 */
@Service
public class TrackRecordService {

    // Display order for the per-market breakdown; markets absent from the data are skipped.
    private static final List<String> MARKET_ORDER =
        List.of("total", "moneyline", "run_line", "hr", "hit");

    private final TrackRecordRepository repo;

    public TrackRecordService(TrackRecordRepository repo) {
        this.repo = repo;
    }

    @Cacheable(cacheNames = "trackRecord", key = "#days")
    public TrackRecordResponse trackRecord(int days) {
        LocalDate since = LocalDate.now().minusDays(Math.max(days, 1));
        List<SettledPick> picks = repo.settledSince(since);

        Acc overall = new Acc("Overall");
        Map<String, Acc> byMarket = new LinkedHashMap<>();
        Map<String, Acc> byBook = new LinkedHashMap<>();
        // Conviction tiers. A Lotto pick (longshot moonshot) is its own bucket so its different
        // risk profile doesn't muddy the Standard record; absent the lotto column it's never set,
        // so the tier simply doesn't appear.
        Acc strong = new Acc("Strong");
        Acc standard = new Acc("Standard");
        Acc lotto = new Acc("Lotto");

        // Distinct model versions the record spans (disclosed, not filtered — the track record is
        // the product's, across version bumps). Sorted for a stable badge.
        TreeSet<String> versions = new TreeSet<>();
        // Brier over decided (win/loss) picks only.
        double brierSum = 0.0;
        int brierN = 0;
        // Per-day equity, accumulated in time order (picks arrive oldest-first).
        List<EquityPointDto> equity = new ArrayList<>();
        LocalDate curDay = null;
        double cumUnits = 0.0;
        int cumWins = 0;
        int cumLosses = 0;
        LocalDate asOf = null;

        for (SettledPick p : picks) {
            Outcome o = classify(p);
            if (o == Outcome.VOID) {
                continue;  // postponed/cancelled — never placed, excluded from the record
            }
            asOf = p.slateDate();
            if (p.modelVersion() != null) versions.add(p.modelVersion());
            double units = unitsFor(o, p.priceAmerican());

            overall.add(o, units, p.clv());
            byMarket.computeIfAbsent(p.market(), Acc::new).add(o, units, p.clv());
            byBook.computeIfAbsent(p.book() == null ? "?" : p.book(), Acc::new)
                .add(o, units, p.clv());
            (p.lotto() ? lotto : p.strong() ? strong : standard).add(o, units, p.clv());

            if (o != Outcome.PUSH) {
                double outcome = o == Outcome.WIN ? 1.0 : 0.0;
                double d = p.modelProb() - outcome;
                brierSum += d * d;
                brierN++;
            }

            // Roll up the equity curve a day at a time.
            if (curDay != null && !p.slateDate().equals(curDay)) {
                equity.add(new EquityPointDto(curDay.toString(), round(cumUnits), cumWins, cumLosses));
            }
            curDay = p.slateDate();
            cumUnits += units;
            if (o == Outcome.WIN) cumWins++;
            else if (o == Outcome.LOSS) cumLosses++;
        }
        if (curDay != null) {
            equity.add(new EquityPointDto(curDay.toString(), round(cumUnits), cumWins, cumLosses));
        }

        List<RecordSummaryDto> markets = new ArrayList<>();
        for (String m : MARKET_ORDER) {
            Acc a = byMarket.get(m);
            if (a != null && a.n() > 0) markets.add(a.toDto());
        }
        List<RecordSummaryDto> tiers = new ArrayList<>();
        if (strong.n() > 0) tiers.add(strong.toDto());
        if (standard.n() > 0) tiers.add(standard.toDto());
        if (lotto.n() > 0) tiers.add(lotto.toDto());

        // Books in descending slice size — the biggest books first, "?" (no book) wherever it lands.
        List<RecordSummaryDto> books = byBook.values().stream()
            .sorted((a, b) -> Integer.compare(b.n(), a.n()))
            .map(Acc::toDto)
            .toList();

        Double pickBrier = brierN > 0 ? round4(brierSum / brierN) : null;
        int clvN = overall.clvN;
        return new TrackRecordResponse(
            days, asOf == null ? null : asOf.toString(), new ArrayList<>(versions),
            overall.toDto(), markets, tiers, books, equity, pickBrier,
            clvN > 0 ? clvN : null,
            clvN > 0 ? round4((double) overall.clvPositive / clvN) : null,
            clvN > 0 ? round4(overall.clvSum / clvN) : null,
            clvN > 0 ? overall.clvZero : null);
    }

    private enum Outcome { WIN, LOSS, PUSH, VOID }

    private static Outcome classify(SettledPick p) {
        if (p.won() != null) {
            return p.won() ? Outcome.WIN : Outcome.LOSS;
        }
        // Graded with no win/loss: a push has an actual result_value; a void (postponed) doesn't.
        return p.resultValue() != null ? Outcome.PUSH : Outcome.VOID;
    }

    private static double unitsFor(Outcome o, int priceAmerican) {
        return switch (o) {
            case WIN -> decimalOdds(priceAmerican) - 1.0;
            case LOSS -> -1.0;
            default -> 0.0;  // PUSH (VOID is filtered out before this)
        };
    }

    /** American → decimal odds. +150 → 2.50, −120 → 1.833. */
    static double decimalOdds(int american) {
        return american > 0 ? 1.0 + american / 100.0 : 1.0 + 100.0 / -american;
    }

    private static double round(double v) {
        return Math.round(v * 100.0) / 100.0;
    }

    private static double round4(double v) {
        return Math.round(v * 10000.0) / 10000.0;
    }

    /** Mutable record accumulator for one slice (overall / a market / a tier / a book). */
    private static final class Acc {
        private final String label;
        private int wins, losses, pushes;
        private double units;
        // CLV over the slice's picks that had a closing quote (independent of win/loss).
        private double clvSum;
        private int clvN, clvPositive, clvZero;

        Acc(String label) {
            this.label = label;
        }

        void add(Outcome o, double u, Double clv) {
            units += u;
            switch (o) {
                case WIN -> wins++;
                case LOSS -> losses++;
                case PUSH -> pushes++;
                default -> { /* VOID never reaches here */ }
            }
            if (clv != null) {
                clvSum += clv;
                clvN++;
                if (clv > 0) clvPositive++;
                else if (clv == 0) clvZero++;
            }
        }

        int n() {
            return wins + losses + pushes;
        }

        RecordSummaryDto toDto() {
            int decided = wins + losses;
            double winPct = decided > 0 ? (double) wins / decided : 0.0;
            int n = n();
            double roiPct = n > 0 ? units / n * 100.0 : 0.0;
            return new RecordSummaryDto(
                label, n, wins, losses, pushes,
                round4(winPct), round(units), round(roiPct),
                clvN > 0 ? clvN : null,
                clvN > 0 ? round4((double) clvPositive / clvN) : null,
                clvN > 0 ? round4(clvSum / clvN) : null);
        }
    }
}
