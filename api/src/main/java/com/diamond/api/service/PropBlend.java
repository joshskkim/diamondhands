package com.diamond.api.service;

import com.diamond.api.repository.ClearRateRepository.ClearRates;

import java.util.Map;

/**
 * Regresses a model probability toward the player's demonstrated clear rate.
 *
 * <p>Empirical-rate shrinkage (Jun 2026): the multiplicative adjustment chain
 * (park × pitcher × weather) can stack a league-average bat to the rate clamp — the board
 * once advertised an 85% hit prob for a player whose own season clear-rate was 46%.
 * Two-stage blend:
 * <ol>
 *   <li>the player's season clear-rate is regressed toward the LEAGUE clear-rate by sample
 *       size ({@link #PRIOR_N} phantom games) — so a 5-game sample can't dodge scrutiny the
 *       way a raw n/(n+K) weight would allow;</li>
 *   <li>the model's probability is blended toward that stabilized empirical target, with
 *       the empirical side's weight growing with evidence.</li>
 * </ol>
 * The model still moves the number (that's its job); it just can't double a 63-game track
 * record or ride a 5-game rookie sample to the top of the board.
 *
 * <p><b>A blend is only legitimate at the line the clear rate measures.</b> Clear rates are
 * per-event: {@code tb} counts games with 2+ total bases, i.e. over 1.5 and nothing else.
 * Regressing a P(over 2.5 TB) toward that rate would pull it toward a different event's
 * frequency. So {@link #blend(String, double, Double, ClearRates)} blends only at the
 * canonical line below, and passes everything else — off-line quotes, and every pitcher
 * market, which has no clear rate at all — through untouched.
 */
final class PropBlend {

    private PropBlend() {}

    private static final int SHRINK_K = 60;
    private static final int PRIOR_N = 25;

    /** The one line a market's clear rate measures, and the league-average rate at it —
     *  the prior a thin empirical sample regresses toward. tb/hrr measured over 2026
     *  player_game_stats (share of starter games with 2+ total bases / 2+ hits+runs+RBI);
     *  hit/hr/bb are the long-standing 1+ rates. Mirrors ClearRateRepository's SQL. */
    private record Canonical(double line, double leagueRate) {}

    private static final Map<String, Canonical> CANONICAL = Map.of(
        "hit", new Canonical(0.5, 0.62),
        "hr",  new Canonical(0.5, 0.15),
        "bb",  new Canonical(0.5, 0.30),
        "tb",  new Canonical(1.5, 0.31),
        "hrr", new Canonical(1.5, 0.44));

    /** The league clear-rate for a market at its canonical line. */
    static double leagueRate(String market) {
        Canonical c = CANONICAL.get(market);
        if (c == null) throw new IllegalArgumentException("no clear rate for market: " + market);
        return c.leagueRate();
    }

    /**
     * Blended probability for a prop selection, or {@code raw} unchanged when this
     * market/line has no comparable clear rate (pitcher markets, off-canonical lines).
     * Null in → null out.
     */
    static Double blend(String market, double line, Double raw, ClearRates rates) {
        Canonical c = CANONICAL.get(market);
        if (raw == null || c == null || !PropDistribution.sameLine(c.line(), line)) {
            return raw;
        }
        return blend(raw, seasonRate(market, rates), nSeason(market, rates), c.leagueRate());
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

    /** Sample size behind a market's season clear-rate. H+R+RBI counts only games with
     *  runs/rbi recorded (boxscore-only columns) so a pre-backfill history can't pose
     *  as evidence — the blend then correctly regresses toward the league rate. */
    static Integer nSeason(String market, ClearRates rates) {
        if (rates == null) return null;
        return "hrr".equals(market) ? rates.nHrrSeason() : rates.nSeason();
    }

    static Double seasonRate(String market, ClearRates rates) {
        return rateFor(market, rates, false);
    }

    static Double rateFor(String market, ClearRates rates, boolean l10) {
        if (rates == null) return null;
        return switch (market) {
            case "hit" -> l10 ? rates.hitL10() : rates.hitSeason();
            case "hr"  -> l10 ? rates.hrL10()  : rates.hrSeason();
            case "bb"  -> l10 ? rates.bbL10()  : rates.bbSeason();
            case "tb"  -> l10 ? rates.tbL10()  : rates.tbSeason();
            case "hrr" -> l10 ? rates.hrrL10() : rates.hrrSeason();
            default -> null;
        };
    }
}
