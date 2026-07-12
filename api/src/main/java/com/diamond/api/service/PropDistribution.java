package com.diamond.api.service;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Reads P(over a line) out of the two shapes the projection engine stores its per-player
 * prop distributions in. Shared by the prop board and the per-game odds panel so the two
 * can never disagree about what the model says.
 *
 * <p>Two shapes, because two engines:
 * <ul>
 *   <li><b>Count histograms</b> (game_sim_batter_props.tb_hist / hrr_hist,
 *       game_sim_pitcher_props.hits_hist / er_hist) come from the Monte-Carlo simulator
 *       and price ANY half-line.</li>
 *   <li><b>Threshold ladders</b> (pitcher_projections.workload -&gt; p_k / p_outs) come from
 *       the closed-form workload model, which materializes only a fixed grid of lines.
 *       A book line off that grid can't be priced — see {@link #ladderProb}.</li>
 * </ul>
 *
 * <p>Every method returns {@code null} rather than {@code 0.0} for "no model here". That
 * distinction is load-bearing: a 0% over silently becomes a confident 100% under.
 */
final class PropDistribution {

    private PropDistribution() {}

    /** True when a simulator histogram is usable (the game had a sim row). Mirrors the
     *  emptiness guard in {@link #histPOver}: without it a card would render all-0% (a
     *  bogus 100% under) instead of being suppressed. */
    static boolean hasHist(int[] hist, Integer nSims) {
        return hist != null && hist.length > 0 && nSims != null && nSims > 0;
    }

    /** P(over one line) from a simulator count histogram — null (not 0) when the player
     *  has no sim row, so callers drop him instead of ranking a bogus 0%. */
    static Double histProb(int[] hist, Integer nSims, double line) {
        if (!hasHist(hist, nSims)) return null;
        return histPOver(hist, nSims, List.of(line)).get(0);
    }

    /** P(over each line) from a simulator count histogram (bin i = sims with exactly i,
     *  last bin a &gt;=N catch-all). All-zero list when the game had no sim row. */
    static List<Double> histPOver(int[] hist, Integer nSims, List<Double> lines) {
        if (!hasHist(hist, nSims)) {
            return lines.stream().map(l -> (Double) 0.0).toList();
        }
        List<Double> out = new ArrayList<>(lines.size());
        for (double line : lines) {
            int over = 0;
            for (int i = 0; i < hist.length; i++) {
                if (i > line) over += hist[i];
            }
            out.add((double) over / nSims);
        }
        return out;
    }

    /**
     * P(over) from a workload ladder keyed by line ("5.5" -&gt; p), as stored in the
     * {@code workload} jsonb. Exact grid hit when present; otherwise a monotone linear
     * interpolation between the nearest materialized lines below and above (the ladder is
     * monotone in the line, so a straight segment is a faithful in-between). Null when the
     * book line sits outside the materialized range — extrapolating past the grid would
     * invent a tail. Widen the grids in {@code projection/workload.py} to cover more range.
     */
    static Double ladderProb(Map<String, Double> ladder, double line) {
        if (ladder == null || ladder.isEmpty()) return null;
        Double exact = ladder.get(lineKey(line));
        if (exact != null) return exact;
        Double loLine = null, hiLine = null, loProb = null, hiProb = null;
        for (Map.Entry<String, Double> e : ladder.entrySet()) {
            double l = Double.parseDouble(e.getKey());
            if (l < line && (loLine == null || l > loLine)) { loLine = l; loProb = e.getValue(); }
            if (l > line && (hiLine == null || l < hiLine)) { hiLine = l; hiProb = e.getValue(); }
        }
        if (loLine == null || hiLine == null) return null; // off-grid, outside range
        double t = (line - loLine) / (hiLine - loLine);
        return loProb + t * (hiProb - loProb);
    }

    /** A line's canonical string key: 5.50 -&gt; "5.5". Matches the keys Python writes into
     *  the workload jsonb (f"{line}"), and the line-shop selection key the client joins on. */
    static String lineKey(double line) {
        return BigDecimal.valueOf(line).stripTrailingZeros().toPlainString();
    }

    static boolean sameLine(double a, double b) {
        return Math.abs(a - b) < 1e-9;
    }
}
