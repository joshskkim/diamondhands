package com.diamond.api.service;

import com.diamond.api.dto.AccuracyPointDto;
import com.diamond.api.dto.AccuracyResponse;
import com.diamond.api.dto.CalibrationBucketDto;
import com.diamond.api.dto.MarketAccuracyDto;
import com.diamond.api.repository.AccuracyRepository;
import com.diamond.api.repository.AccuracyRepository.AccuracyRow;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Serves the rolling projection-accuracy trend: the daily_accuracy snapshots for the current
 * model version, grouped per market into a per-day series (brier vs baseline) plus the latest
 * day's calibration curve. total_runs carries an MAE instead of a Brier.
 */
@Service
public class AccuracyService {

    // Display/iteration order; markets absent from the data are simply skipped.
    private static final List<String> MARKET_ORDER =
        List.of("hit1plus", "hit2plus", "hr", "k1plus", "total_runs");

    private final AccuracyRepository repo;
    private final ObjectMapper mapper = new ObjectMapper();

    public AccuracyService(AccuracyRepository repo) {
        this.repo = repo;
    }

    @Cacheable(cacheNames = "accuracy", key = "#days")
    public AccuracyResponse accuracy(int days) {
        String version = repo.latestModelVersion();
        if (version == null) {
            return new AccuracyResponse(days, null, List.of());
        }
        LocalDate since = LocalDate.now().minusDays(days);
        List<AccuracyRow> rows = repo.recentRows(version, since);

        Map<String, List<AccuracyRow>> byMarket = new LinkedHashMap<>();
        for (String m : MARKET_ORDER) {
            byMarket.put(m, new ArrayList<>());
        }
        for (AccuracyRow r : rows) {
            byMarket.computeIfAbsent(r.market(), k -> new ArrayList<>()).add(r);
        }

        List<MarketAccuracyDto> markets = new ArrayList<>();
        for (Map.Entry<String, List<AccuracyRow>> e : byMarket.entrySet()) {
            List<AccuracyRow> marketRows = e.getValue();
            if (marketRows.isEmpty()) {
                continue;
            }
            List<AccuracyPointDto> series = new ArrayList<>();
            for (AccuracyRow r : marketRows) {
                series.add(new AccuracyPointDto(
                    r.slateDate().toString(), r.n(), r.brier(), r.baselineBrier(), r.ece()));
            }
            // Rows are ordered by date asc, so the last is the most recent.
            AccuracyRow latest = marketRows.get(marketRows.size() - 1);
            markets.add(new MarketAccuracyDto(
                e.getKey(), series, parseCalibration(latest.calibrationJson()), latest.mae()));
        }
        return new AccuracyResponse(days, version, markets);
    }

    /** Parse the stored calibration_buckets JSON ([{lo,hi,n,predicted_mean,actual_rate}, …]). */
    private List<CalibrationBucketDto> parseCalibration(String json) {
        if (json == null || json.isBlank()) {
            return List.of();
        }
        try {
            List<Map<String, Object>> raw = mapper.readValue(json, new TypeReference<>() {});
            List<CalibrationBucketDto> out = new ArrayList<>(raw.size());
            for (Map<String, Object> b : raw) {
                out.add(new CalibrationBucketDto(
                    num(b.get("lo")), num(b.get("hi")), intval(b.get("n")),
                    num(b.get("predicted_mean")), num(b.get("actual_rate"))));
            }
            return out;
        } catch (Exception ex) {
            return List.of();
        }
    }

    private static double num(Object o) {
        return o instanceof Number n ? n.doubleValue() : 0.0;
    }

    private static int intval(Object o) {
        return o instanceof Number n ? n.intValue() : 0;
    }
}
