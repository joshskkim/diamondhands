package com.diamond.api.dto;

import java.util.List;

/**
 * A user's personal Tracker (GET /api/tracker): their tailed Analyst recommendations + the bets
 * they've logged, graded with ROI/CLV — the personal mirror of the model's Report Card.
 */
public record TrackerResponse(TrackerSummary summary, List<TrackerEntry> entries) {

    /** One tracked selection. {@code source} = "agent" (a tailed pick) | "personal" (a logged bet). */
    public record TrackerEntry(
        long id,
        String source,
        String slateDate,
        long gameId,
        String market,
        String side,
        Double line,
        Integer playerId,
        String playerName,
        Integer priceAmerican,
        String book,
        Double stakeUnits,
        Double confidence,   // judge confidence for tailed picks; null for logged bets
        Double modelProb,
        Double fairProb,
        Double edge,
        Boolean won,         // null while unscored or on a push/void
        Double resultValue,
        Double clv,
        boolean scored,
        String status
    ) {}

    /** Rolled-up record + ROI/CLV at the recorded stakes (flat where stake is unset). */
    public record TrackerSummary(
        int picks, int wins, int losses, int pushes,
        double units, double roiPct,
        Integer clvN, Double clvRate, Double avgClv
    ) {}
}
