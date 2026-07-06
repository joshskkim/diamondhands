package com.diamond.api.ai;

import com.diamond.api.service.OddsMath;
import org.springframework.stereotype.Component;

/**
 * Deterministic fractional-Kelly bet sizing. Stake is COMPUTED here, never produced by the
 * language model — the agent may reason about a pick, but the dollars come from a formula it
 * can't hallucinate. Fractional Kelly (default quarter) tames full-Kelly's variance and the
 * model's own calibration error.
 *
 *   f*    = (p*(b+1) - 1) / b        full-Kelly fraction of bankroll
 *   stake = bankroll * kellyFraction * max(f*, 0)
 *
 * where p = model probability, b = decimal odds - 1 (net fractional payout). A non-positive
 * edge yields zero stake (no bet).
 */
@Component
public class KellyCalculator {

    /** Hard cap on the user's Kelly fraction regardless of preference (variance guardrail). */
    public static final double MAX_KELLY_FRACTION = 0.5;

    public record Sizing(double fullKelly, double fraction, double stakeUnits, double stakeUsd, String note) {}

    /**
     * @param modelProb     model's win probability (0-1)
     * @param decimalOdds   the price as a decimal (e.g. +120 -> 2.20)
     * @param bankrollUnits bankroll in units
     * @param unitSizeUsd   dollars per unit (may be null/0 -> stakeUsd is 0)
     * @param kellyFraction the user's fraction (clamped to [0, MAX_KELLY_FRACTION])
     */
    public Sizing size(double modelProb, double decimalOdds, double bankrollUnits,
                       Double unitSizeUsd, double kellyFraction) {
        double b = decimalOdds - 1.0;
        if (b <= 0 || modelProb <= 0 || modelProb >= 1 || bankrollUnits <= 0) {
            return new Sizing(0, clampFraction(kellyFraction), 0, 0, "no stake (invalid inputs or no edge)");
        }
        double fStar = (modelProb * (b + 1.0) - 1.0) / b;
        double fraction = clampFraction(kellyFraction);
        if (fStar <= 0) {
            return new Sizing(round(fStar), fraction, 0, 0, "no stake (model has no edge at this price)");
        }
        double stakeUnits = round(bankrollUnits * fraction * fStar);
        double stakeUsd = unitSizeUsd == null ? 0 : round(stakeUnits * unitSizeUsd);
        String note = String.format("%.0f%%-Kelly of a %.0f%% full-Kelly edge on a %.0f-unit bankroll",
            fraction * 100, fStar * 100, bankrollUnits);
        return new Sizing(round(fStar), fraction, stakeUnits, stakeUsd, note);
    }

    public static double clampFraction(double f) {
        if (Double.isNaN(f) || f < 0) {
            return 0;
        }
        return Math.min(f, MAX_KELLY_FRACTION);
    }

    /** American odds -> decimal odds. Delegates to {@link OddsMath} (the canonical home). */
    public static double americanToDecimal(int american) {
        return OddsMath.americanToDecimal(american);
    }

    private static double round(double v) {
        return Math.round(v * 10000.0) / 10000.0;
    }
}
