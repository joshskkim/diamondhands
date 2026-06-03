package com.diamond.api.service;

/**
 * Derives game-market probabilities from our projected team runs by treating each side's
 * runs as an independent Poisson variable (λ = expected runs). Probabilities are computed
 * by summing over a bounded run grid — exact enough for an edge signal and dependency-free.
 *
 * Independence ignores run correlation (weather, park, game state), so treat these as a
 * first-order model edge, not a calibrated win probability.
 */
public final class OddsModel {

    private static final int MAX_RUNS = 30;

    private final double[] ph;
    private final double[] pa;

    public OddsModel(double lambdaHome, double lambdaAway) {
        this.ph = poisson(lambdaHome);
        this.pa = poisson(lambdaAway);
    }

    /** PMF over 0..MAX_RUNS via the recurrence p_k = p_{k-1} * λ/k (no factorials). */
    private static double[] poisson(double lambda) {
        double[] p = new double[MAX_RUNS + 1];
        double term = Math.exp(-lambda); // k = 0
        p[0] = term;
        for (int k = 1; k <= MAX_RUNS; k++) {
            term *= lambda / k;
            p[k] = term;
        }
        return p; // negligible tail beyond MAX_RUNS for MLB-scale λ
    }

    /** P(home wins); MLB has no ties, so an equal-runs grid cell is split 50/50. */
    public double pHomeWin() {
        double win = 0, tie = 0;
        for (int h = 0; h <= MAX_RUNS; h++) {
            for (int a = 0; a <= MAX_RUNS; a++) {
                double joint = ph[h] * pa[a];
                if (h > a) win += joint;
                else if (h == a) tie += joint;
            }
        }
        return win + 0.5 * tie;
    }

    /** P(home_runs + away_runs > line). */
    public double pTotalOver(double line) {
        double over = 0;
        for (int h = 0; h <= MAX_RUNS; h++) {
            for (int a = 0; a <= MAX_RUNS; a++) {
                if (h + a > line) over += ph[h] * pa[a];
            }
        }
        return over;
    }

    /** P(home covers its run line); homeLine is the signed spread, e.g. -1.5. */
    public double pHomeCover(double homeLine) {
        double cover = 0;
        for (int h = 0; h <= MAX_RUNS; h++) {
            for (int a = 0; a <= MAX_RUNS; a++) {
                if ((h - a) > -homeLine) cover += ph[h] * pa[a];
            }
        }
        return cover;
    }

    /** P(away covers its run line); awayLine is the signed spread, e.g. +1.5. */
    public double pAwayCover(double awayLine) {
        double cover = 0;
        for (int h = 0; h <= MAX_RUNS; h++) {
            for (int a = 0; a <= MAX_RUNS; a++) {
                if ((a - h) > -awayLine) cover += ph[h] * pa[a];
            }
        }
        return cover;
    }
}
