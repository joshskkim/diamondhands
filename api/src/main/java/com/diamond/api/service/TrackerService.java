package com.diamond.api.service;

import com.diamond.api.ai.KellyCalculator;
import com.diamond.api.ai.UserPreferences;
import com.diamond.api.dto.TrackerResponse;
import com.diamond.api.dto.TrackerResponse.TrackerEntry;
import com.diamond.api.dto.TrackerResponse.TrackerSummary;
import com.diamond.api.repository.AgentRepository;
import com.diamond.api.repository.TrackerRepository;
import com.diamond.api.repository.UserPreferenceRepository;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * The personal Tracker: tail a pick (compute the Kelly stake and record it) and read back the
 * user's tailed picks + logged bets graded with ROI/CLV. Reuses {@link KellyCalculator} (stake is
 * computed, never guessed), {@link AgentRepository} (the same write path the agent's
 * save_recommendation uses), and mirrors {@link TrackRecordService}'s record/units/ROI math.
 */
@Service
public class TrackerService {

    private final TrackerRepository repo;
    private final UserPreferenceRepository prefsRepo;
    private final AgentRepository agentRepo;
    private final KellyCalculator kelly;

    public TrackerService(TrackerRepository repo, UserPreferenceRepository prefsRepo,
                          AgentRepository agentRepo, KellyCalculator kelly) {
        this.repo = repo;
        this.prefsRepo = prefsRepo;
        this.agentRepo = agentRepo;
        this.kelly = kelly;
    }

    public record TailResult(Double stakeUnits, boolean alreadyTracked, String message) {}

    /** Tail a board pick into the user's tracker with a deterministically-sized Kelly stake. */
    public TailResult tail(long userId, long gameId, String market, String side, Double line,
                           Integer playerId, String playerName, int priceAmerican, String book,
                           double modelProb, double fairProb, Double confidence) {
        LocalDate slate = LocalDate.now();
        if (repo.recommendationExists(userId, slate, gameId, market, side, playerId)) {
            return new TailResult(null, true, "Already in your tracker.");
        }
        double decimal = KellyCalculator.americanToDecimal(priceAmerican);
        double edge = modelProb - fairProb;
        double evPct = modelProb * decimal - 1.0;

        UserPreferences prefs = prefsRepo.findOrDefault(userId);
        Double stakeUnits = null;
        String message;
        if (prefs.canSize()) {
            KellyCalculator.Sizing s = kelly.size(modelProb, decimal, prefs.bankrollUnits(),
                prefs.unitSizeUsd(), prefs.kellyFraction());
            stakeUnits = s.stakeUnits();
            message = String.format("Tailed — %.2f-unit Kelly stake.", s.stakeUnits());
        } else {
            message = "Tailed. Set a bankroll in the Analyst to get Kelly sizing.";
        }

        agentRepo.insertRecommendation(null, userId, slate, gameId, market, side, line, playerId,
            playerName, modelProb, fairProb, round4(edge), round4(evPct), priceAmerican, book,
            stakeUnits, confidence);
        return new TailResult(stakeUnits, false, message);
    }

    /** The user's tracked picks + bets, newest first, with a rolled-up record / ROI / CLV. */
    public TrackerResponse tracked(long userId) {
        List<TrackerEntry> entries = new ArrayList<>(repo.findRecommendations(userId));
        entries.addAll(repo.findBets(userId));
        entries.sort(Comparator.comparing(TrackerEntry::slateDate).reversed());
        return new TrackerResponse(summarize(entries), entries);
    }

    private static TrackerSummary summarize(List<TrackerEntry> entries) {
        int wins = 0, losses = 0, pushes = 0, clvN = 0, clvPositive = 0;
        double units = 0.0, clvSum = 0.0;
        int graded = 0;
        for (TrackerEntry e : entries) {
            if (e.clv() != null) {
                clvN++;
                clvSum += e.clv();
                if (e.clv() > 0) clvPositive++;
            }
            if (!e.scored()) {
                continue; // still pending
            }
            double stake = e.stakeUnits() != null && e.stakeUnits() > 0 ? e.stakeUnits() : 1.0;
            if (e.won() == null) {
                if (e.resultValue() != null) {   // graded with no win/loss = push
                    pushes++;
                    graded++;
                }
                continue; // void (no result_value) excluded
            }
            graded++;
            if (e.won()) {
                wins++;
                units += stake * (KellyCalculator.americanToDecimal(
                    e.priceAmerican() == null ? -110 : e.priceAmerican()) - 1.0);
            } else {
                losses++;
                units -= stake;
            }
        }
        double roiPct = graded > 0 ? units / graded * 100.0 : 0.0;
        return new TrackerSummary(
            graded, wins, losses, pushes, round2(units), round2(roiPct),
            clvN > 0 ? clvN : null,
            clvN > 0 ? round4((double) clvPositive / clvN) : null,
            clvN > 0 ? round4(clvSum / clvN) : null);
    }

    private static double round2(double v) {
        return Math.round(v * 100.0) / 100.0;
    }

    private static double round4(double v) {
        return Math.round(v * 10000.0) / 10000.0;
    }
}
