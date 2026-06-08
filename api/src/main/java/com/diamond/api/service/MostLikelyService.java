package com.diamond.api.service;

import com.diamond.api.dto.*;
import com.diamond.api.repository.MostLikelyRepository;
import com.diamond.api.repository.MostLikelyRepository.PropRow;
import com.diamond.api.repository.MostLikelyRepository.SimRow;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.function.Function;

/**
 * Assembles the "Most Likely" board from the game simulator's stored outputs: full-game
 * totals vs the consensus book line (edge + P(over) from the sim's run histogram), the
 * first-five-innings (F5) markets, NRFI/YRFI, and the top player props. Read-only and
 * cached per date.
 */
@Service
public class MostLikelyService {

    private static final int PROP_TOP_N = 5;
    /** Ignore wafer-thin total leans below this many runs when labelling over/under. */
    private static final double LEAN_EPS = 0.05;

    private final MostLikelyRepository repo;

    public MostLikelyService(MostLikelyRepository repo) {
        this.repo = repo;
    }

    @Cacheable(cacheNames = "mostLikely", key = "#date.toString()")
    public MostLikelyResponse board(LocalDate date) {
        List<SimRow> sims = repo.findSimRows(date);
        return new MostLikelyResponse(
            date.toString(), totals(sims), nrfi(sims), f5(sims), props(repo.findPropRows(date)));
    }

    // ── Full-game totals vs the line ──────────────────────────────────────────
    private List<GameTotalDto> totals(List<SimRow> sims) {
        List<GameTotalDto> out = new ArrayList<>();
        for (SimRow s : sims) {
            Double edge = s.bookTotal() == null ? null : round(s.expectedTotal() - s.bookTotal(), 2);
            Double pOver = pOver(s.totalHist(), s.nSims(), s.bookTotal());
            out.add(new GameTotalDto(
                s.gameId(), s.matchup(), round(s.expectedTotal(), 2),
                s.bookTotal() == null ? null : round(s.bookTotal(), 1),
                edge, pOver, lean(edge)));
        }
        // Biggest over-leans first, biggest under-leans last; games w/o a line at the end.
        out.sort(Comparator.comparingDouble((GameTotalDto g) ->
            g.edge() == null ? Double.NEGATIVE_INFINITY : g.edge()).reversed());
        return out;
    }

    // ── NRFI / YRFI ───────────────────────────────────────────────────────────
    private List<NrfiDto> nrfi(List<SimRow> sims) {
        List<NrfiDto> out = new ArrayList<>();
        for (SimRow s : sims) {
            double yrfi = s.pYrfi();
            double nrfi = 1.0 - yrfi;
            boolean leanNrfi = nrfi >= yrfi;
            out.add(new NrfiDto(
                s.gameId(), s.matchup(), round(yrfi, 3), round(nrfi, 3),
                leanNrfi ? "NRFI" : "YRFI", round(Math.max(nrfi, yrfi), 3)));
        }
        out.sort(Comparator.comparingDouble(NrfiDto::leanProb).reversed());
        return out;
    }

    // ── First five innings (F5) ────────────────────────────────────────────────
    private List<F5Dto> f5(List<SimRow> sims) {
        List<F5Dto> out = new ArrayList<>();
        for (SimRow s : sims) {
            Double edge = s.bookF5Total() == null ? null : round(s.f5Total() - s.bookF5Total(), 2);
            Double pOver = pOver(s.f5TotalHist(), s.nSims(), s.bookF5Total());
            boolean homeFav = s.f5PHomeLead() >= s.f5PAwayLead();
            out.add(new F5Dto(
                s.gameId(), s.matchup(), round(s.f5Total(), 2),
                s.bookF5Total() == null ? null : round(s.bookF5Total(), 1),
                edge, pOver,
                homeFav ? s.homeAbbr() : s.awayAbbr(),
                round(homeFav ? s.f5PHomeLead() : s.f5PAwayLead(), 3),
                round(s.f5PTie(), 3)));
        }
        out.sort(Comparator.comparingDouble((F5Dto g) ->
            g.edge() == null ? Double.NEGATIVE_INFINITY : g.edge()).reversed());
        return out;
    }

    // ── Player prop leaderboards ───────────────────────────────────────────────
    private PropLeadersDto props(List<PropRow> rows) {
        return new PropLeadersDto(
            topProps(rows, PropRow::pHit1),
            topProps(rows, PropRow::pHr),
            topProps(rows, PropRow::expectedTb),
            topProps(rows, PropRow::pK1));
    }

    private List<PropLeaderDto> topProps(List<PropRow> rows, Function<PropRow, Double> metric) {
        return rows.stream()
            .filter(r -> metric.apply(r) != null)
            .sorted(Comparator.comparingDouble((PropRow r) -> metric.apply(r)).reversed())
            .limit(PROP_TOP_N)
            .map(r -> new PropLeaderDto(
                r.playerId(), r.player(), r.team(), r.matchup(), round(metric.apply(r), 3)))
            .toList();
    }

    // ── Helpers ─────────────────────────────────────────────────────────────────
    private static Double pOver(int[] hist, int nSims, Double line) {
        if (line == null || hist == null || hist.length == 0 || nSims <= 0) return null;
        int over = 0;
        for (int i = 0; i < hist.length; i++) {
            if (i > line) over += hist[i];
        }
        return round((double) over / nSims, 3);
    }

    private static String lean(Double edge) {
        if (edge == null) return null;
        if (edge > LEAN_EPS) return "over";
        if (edge < -LEAN_EPS) return "under";
        return "even";
    }

    private static double round(double v, int places) {
        double f = Math.pow(10, places);
        return Math.round(v * f) / f;
    }

    private static Double round(Double v, int places) {
        return v == null ? null : round((double) v, places);
    }
}
