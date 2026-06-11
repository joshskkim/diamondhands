package com.diamond.api.service;

import com.diamond.api.dto.PropBoardPickDto;
import com.diamond.api.dto.PropBoardResponse;
import com.diamond.api.repository.PropBoardRepository;
import com.diamond.api.repository.PropBoardRepository.BestPrice;
import com.diamond.api.repository.PropBoardRepository.ClearRates;
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
                          Function<SlateRow, Double> weather) {}

    // Batter K has no odds-market counterpart in our data (books we ingest don't
    // quote it), so its price fields are always null.
    private static final List<Market> MARKETS = List.of(
        new Market("hit", "hit", SlateRow::pHit1, SlateRow::adjWeatherHits),
        new Market("hr",  "hr",  SlateRow::pHr,   SlateRow::adjWeatherHr),
        new Market("k",   null,  SlateRow::pK1,   r -> null));

    private final PropBoardRepository repo;

    public PropBoardService(PropBoardRepository repo) {
        this.repo = repo;
    }

    @Cacheable(cacheNames = "propBoard", key = "#date.toString()")
    public PropBoardResponse board(LocalDate date) {
        List<SlateRow> rows = repo.findSlateRows(date);
        List<PropBoardPickDto> picks = new ArrayList<>();
        // One player at most once across the board — three cards of the same batter
        // is a worse display than the marginally-less-likely runner-up.
        Set<Integer> used = new HashSet<>();

        for (Market m : MARKETS) {
            rows.stream()
                .filter(r -> m.prob().apply(r) != null && r.expectedPa() != null)
                .filter(r -> !used.contains(r.playerId()))
                .max(Comparator.comparingDouble(r -> m.prob().apply(r)))
                .ifPresent(r -> {
                    used.add(r.playerId());
                    picks.add(toPick(m, r, date));
                });
        }
        return new PropBoardResponse(date.toString(), rows.size(), picks);
    }

    private PropBoardPickDto toPick(Market m, SlateRow r, LocalDate date) {
        double prob = m.prob().apply(r);
        ClearRates rates = repo.findClearRates(r.playerId(), date);
        BestPrice price = m.oddsMarket() == null
            ? null
            : repo.findBestOverPrice(date, r.playerId(), m.oddsMarket());

        return new PropBoardPickDto(
            m.key(), 0.5,
            r.gameId(), r.matchup(),
            r.playerId(), r.player(), r.team(),
            r.lineupPosition(), r.lineupConfirmed(), r.expectedPa(),
            round(prob, 4),
            r.opposingPitcherId(), r.opposingPitcher(), r.pitcherDataQuality(),
            r.matchupXwoba(), r.matchupQuality(),
            r.adjPark(), r.adjPitcher(), m.weather().apply(r),
            r.stadium(),
            rateFor(m.key(), rates, true),
            rateFor(m.key(), rates, false),
            rates == null ? null : rates.nSeason(),
            price == null ? null : price.bookmaker(),
            price == null ? null : price.priceAmerican(),
            price == null ? null : price.priceDecimal(),
            price == null ? null : round(prob * price.priceDecimal() - 1.0, 4));
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
}
