package com.diamond.api.dto;

import java.util.List;

/**
 * GET /api/track-record?days=N — the live track record of the published Model's Picks over the
 * trailing window. This is how the recorded picks actually performed (record, units, ROI), broken
 * down overall, by market, and by conviction tier.
 *
 * <p>{@code pickBrier} is the Brier score of the picks' model probabilities against their outcomes.
 * IMPORTANT: it measures only this biased, +EV-selected sample of plays — it is NOT a calibration
 * of the whole model. The unbiased per-market calibration lives in /api/accuracy (every projection,
 * not just the ones we bet). The Report Card presents the two side by side as distinct things:
 * "how the published picks did" vs. "how well-calibrated the model is".
 *
 * <p>CLV (closing-line value) is the betting north star: of the settled picks for which a closing
 * quote was found, {@code clvRate} is the share with positive CLV and {@code avgClv} the mean CLV
 * (de-vigged probability points we beat the close by). Positive CLV is the best small-sample
 * predictor of long-run edge — but it needs a few hundred picks to be trustworthy, so {@code clvN}
 * is reported alongside as the sample size and both are null until any CLV is captured.
 */
public record TrackRecordResponse(
    int days,
    String asOf,                       // most recent settled slate date, or null when empty
    List<String> modelVersions,        // distinct model versions in the window (the record spans these)
    RecordSummaryDto overall,
    List<RecordSummaryDto> byMarket,
    List<RecordSummaryDto> byTier,     // Strong / Standard
    List<EquityPointDto> equity,       // per-day cumulative units
    Double pickBrier,                  // null when no decided picks in the window
    Integer clvN,                      // settled picks with a closing quote (CLV sample size)
    Double clvRate,                    // share of clvN with positive CLV, or null when clvN == 0
    Double avgClv                      // mean CLV over clvN, or null when clvN == 0
) {}
