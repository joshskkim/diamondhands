package com.diamond.api.service;

/**
 * The one home for sportsbook price math. Every conversion between american/decimal odds
 * and probability, and every EV/de-vig formula, lives here — services must not re-derive
 * these inline (they had drifted into three copies before consolidation).
 */
public final class OddsMath {

    private OddsMath() {}

    /** American odds -> decimal odds: +120 -> 2.20, -150 -> 1.6667. */
    public static double americanToDecimal(int american) {
        return american >= 0 ? 1.0 + american / 100.0 : 1.0 + 100.0 / -((double) american);
    }

    /** Expected value per unit staked at a decimal price; null when the model has no number. */
    public static Double ev(Double modelProb, double decimalOdds) {
        return modelProb == null ? null : modelProb * decimalOdds - 1.0;
    }

    /**
     * No-vig fair probability for one side of a two-way market: its implied probability
     * divided by the two-sided implied sum. Null when the market can't be de-vigged
     * (missing side or degenerate sum).
     */
    public static Double fairShare(Double sideImplied, Double impliedSum) {
        if (sideImplied == null || impliedSum == null || impliedSum <= 0) return null;
        return sideImplied / impliedSum;
    }
}
