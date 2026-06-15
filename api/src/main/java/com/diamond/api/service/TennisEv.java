package com.diamond.api.service;

import com.diamond.api.dto.TennisEvDto;

/**
 * Self-contained match-winner de-vig + EV for tennis (the MLB OddsService/OddsModel
 * is Poisson-runs specific, so tennis gets its own ~tiny calculator).
 *
 * Two-way de-vig: fair_a = implied_a / (implied_a + implied_b). Using the best price
 * on each side (lowest vig) approximates a no-vig market. Exactly one side has
 * non-negative edge vs fair; that is the model's "best play".
 */
public final class TennisEv {

    private TennisEv() {}

    /** Best match-winner play, or null when the projection or both prices are missing. */
    public static TennisEvDto bestPlay(
            Double pWinA,
            Integer amA, Double decA, Double impA, String bookA, String nameA,
            Integer amB, Double decB, Double impB, String bookB, String nameB) {

        if (pWinA == null || decA == null || decB == null || impA == null || impB == null) {
            return null;
        }
        double sum = impA + impB;
        if (sum <= 0) return null;

        double fairA = impA / sum;
        double modelA = pWinA;
        double edgeA = modelA - fairA;

        if (edgeA >= 0) {
            double ev = modelA * (decA - 1.0) - (1.0 - modelA);
            return new TennisEvDto("player_a", nameA, bookA, amA, decA,
                round(modelA, 4), round(fairA, 4), round(edgeA * 100, 2), round(ev * 100, 2));
        }
        double fairB = 1.0 - fairA;
        double modelB = 1.0 - modelA;
        double edgeB = modelB - fairB;
        double ev = modelB * (decB - 1.0) - (1.0 - modelB);
        return new TennisEvDto("player_b", nameB, bookB, amB, decB,
            round(modelB, 4), round(fairB, 4), round(edgeB * 100, 2), round(ev * 100, 2));
    }

    private static double round(double v, int places) {
        double f = Math.pow(10, places);
        return Math.round(v * f) / f;
    }
}
