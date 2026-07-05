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
 * ±1.5 run-line cover leans, NRFI/YRFI, and the top player props. Read-only and
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
            date.toString(), totals(sims), nrfi(sims), runLine(sims), props(repo.findPropRows(date)));
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

    // ── Run line (±1.5 spread) ─────────────────────────────────────────────────
    // The four cover probs available per game (no push on a .5 line, so each -1.5 side
    // and its opposite +1.5 are complements):
    //   home -1.5 = pHomeCover15         away +1.5 = pAwayCover15 (= 1 - pHomeCover15)
    //   away -1.5 = 1 - pHomeCoverPlus15  home +1.5 = pHomeCoverPlus15
    private List<RunLineDto> runLine(List<SimRow> sims) {
        List<RunLineDto> out = new ArrayList<>();
        for (SimRow s : sims) {
            boolean haveOdds = s.bookFavImplied() != null && s.bookDogImplied() != null
                && s.bookFavSide() != null;
            // Edge path needs the +1.5 column too (null on pre-V69 rows → fall back).
            if (haveOdds && s.pHomeCoverPlus15() != null) {
                out.add(edgeRunLine(s));
            } else {
                out.add(favoriteRunLine(s));
            }
        }
        // Strongest cover edges first; games without run-line odds fall to the bottom.
        out.sort(Comparator.comparingDouble((RunLineDto g) ->
            g.edge() == null ? Double.NEGATIVE_INFINITY : g.edge()).reversed());
        return out;
    }

    /** With odds + the +1.5 column: emit whichever side (favorite -1.5 or underdog +1.5)
     *  carries the better de-vigged edge, labeled explicitly. */
    private RunLineDto edgeRunLine(SimRow s) {
        boolean homeIsBookFav = "home".equals(s.bookFavSide());
        // The book favorite lays -1.5; the model's cover prob for that exact team.
        double favCover = homeIsBookFav ? s.pHomeCover15() : (1.0 - s.pHomeCoverPlus15());
        double dogCover = 1.0 - favCover;   // the other team takes +1.5
        double sum = s.bookFavImplied() + s.bookDogImplied();
        double favFair = s.bookFavImplied() / sum;
        double favEdge = favCover - favFair;
        double dogEdge = dogCover - (s.bookDogImplied() / sum);   // = -favEdge

        boolean favBetter = favEdge >= dogEdge;
        String favAbbr = homeIsBookFav ? s.homeAbbr() : s.awayAbbr();
        String dogAbbr = homeIsBookFav ? s.awayAbbr() : s.homeAbbr();
        if (favBetter) {
            return new RunLineDto(s.gameId(), s.matchup(), favAbbr,
                homeIsBookFav ? "home" : "away", -1.5,
                round(favCover, 3), -1.5, round(favEdge, 3));
        }
        return new RunLineDto(s.gameId(), s.matchup(), dogAbbr,
            homeIsBookFav ? "away" : "home", 1.5,
            round(dogCover, 3), 1.5, round(dogEdge, 3));
    }

    /** No odds (or a pre-V69 row missing the +1.5 column): the old framing — the sim's
     *  favorite laying -1.5, no edge. When the +1.5 column is present, both teams' -1.5
     *  cover probs are known so the favorite is picked correctly; otherwise the legacy
     *  pHomeCover15 vs pAwayCover15 heuristic (which compared home -1.5 against away +1.5). */
    private RunLineDto favoriteRunLine(SimRow s) {
        double homeMinus15 = s.pHomeCover15();
        double awayMinus15 = s.pHomeCoverPlus15() != null
            ? 1.0 - s.pHomeCoverPlus15()   // away wins by 2+
            : s.pAwayCover15();            // legacy fallback (not a true -1.5 cover)
        boolean homeFav = homeMinus15 >= awayMinus15;
        return new RunLineDto(s.gameId(), s.matchup(),
            homeFav ? s.homeAbbr() : s.awayAbbr(),
            homeFav ? "home" : "away", -1.5,
            round(homeFav ? homeMinus15 : awayMinus15, 3), null, null);
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
