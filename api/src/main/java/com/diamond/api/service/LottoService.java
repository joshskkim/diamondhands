package com.diamond.api.service;

import com.diamond.api.dto.BoomPickDto;
import com.diamond.api.repository.LottoRepository;
import com.diamond.api.repository.LottoRepository.CandidateRow;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

/**
 * Picks the "Lotto of the Day" — one home-run boom play. The thesis is the exact case the
 * projection's own last-30 blend underweights: a hitter batting at the bottom of the order who
 * has gone cold, but whose raw power (barrels + ISO) is untouched by the slump, in a park /
 * pitcher / weather setup that amplifies home runs today.
 *
 * <p>Deliberately NOT price-gated (that's the Best Lines board's job) and NOT age-gated — the
 * score reads only power, recent-vs-season form, lineup slot, and today's HR conditions, never
 * birth date or service time. A best HR-over price is attached when one exists, for payout +
 * grading, but never required.
 *
 * <p>boomScore = powerBoost · condBoost · coldFactor · carryFactor (see the constants below).
 * The reference baselines mirror the model's {@code LEAGUE_BARREL_RATE} / {@code LEAGUE_ISO} in
 * ingester/ingester/projection/constants.py.
 */
@Service
public class LottoService {

    // League power baselines (mirror ingester projection/constants.py).
    private static final double LEAGUE_BARREL_RATE = 0.078;
    private static final double LEAGUE_ISO = 0.155;

    // powerBoost = W_BARREL·(barrel/league) + W_ISO·(iso/league); barrel-led, matching the
    // model's HR basis (60/40 barrel+ISO). Must clear POWER_MIN — at least league-average pop,
    // so a slap hitter never reads as a "can hit bombs" sleeper.
    private static final double W_BARREL = 0.6;
    private static final double W_ISO = 0.4;
    private static final double POWER_MIN = 1.0;

    // "Cold" = last-30 xwOBA at least COLD_MIN below the season mark; the deeper the slump
    // (relative to true talent), the more the market and our projection sleep on the bat.
    private static final double COLD_MIN = 0.015;
    private static final double COLD_WEIGHT = 5.0;

    // Today's HR multipliers (park·pitcher·weather) must not be actively hostile.
    private static final double COND_MIN = 0.98;

    // Long-ball carry is a modest tiebreaker, not a driver: every foot of projected carry over
    // CARRY_REF nudges the score, scaled by CARRY_WEIGHT. LONG_BALL_FT matches the web HR card's
    // "top-tier carry" badge threshold.
    private static final double CARRY_REF_FT = 410.0;
    private static final double CARRY_WEIGHT = 0.003;
    private static final double LONG_BALL_FT = 430.0;

    private final LottoRepository repo;

    public LottoService(LottoRepository repo) {
        this.repo = repo;
    }

    // unless: the cache rejects nulls (disableCachingNullValues) — a no-pick slate returns null,
    // so skip caching it rather than throw. Null is cheap to recompute and clears once a pick
    // qualifies (lineups/odds move through the day).
    @Cacheable(cacheNames = "lotto", key = "#date", unless = "#result == null")
    public BoomPickDto lottoOfTheDay(LocalDate date) {
        BoomPickDto best = null;
        for (CandidateRow r : repo.findCandidates(date)) {
            double coldGap = r.xwoba() - r.xwobaL30();
            if (coldGap < COLD_MIN) continue;                       // not cold enough
            double powerBoost = W_BARREL * (r.barrelRate() / LEAGUE_BARREL_RATE)
                              + W_ISO * (r.isoSeason() / LEAGUE_ISO);
            if (powerBoost < POWER_MIN) continue;                   // not enough raw pop
            double condBoost = r.adjPark() * r.adjPitcher() * r.adjWeatherHr();
            if (condBoost < COND_MIN) continue;                     // today actively hurts HRs

            double carryFactor = r.hrDistanceFt() == null ? 1.0
                : 1.0 + Math.max(0.0, r.hrDistanceFt() - CARRY_REF_FT) * CARRY_WEIGHT;
            double boomScore = powerBoost * condBoost * (1.0 + COLD_WEIGHT * coldGap) * carryFactor;

            if (best == null || boomScore > best.boomScore()) {
                best = toDto(r, coldGap, condBoost, boomScore);
            }
        }
        return best;
    }

    private BoomPickDto toDto(CandidateRow r, double coldGap, double condBoost, double boomScore) {
        String matchup = r.awayAbbr() + " @ " + r.homeAbbr();
        return new BoomPickDto(
            r.gameId(), matchup, r.playerId(), r.playerName(), r.bats(), r.isHome(),
            r.lineupPosition(), r.opposingPitcher(), r.pHr(),
            r.barrelRate(), r.isoSeason(), r.xwoba(), r.xwobaL30(), coldGap,
            r.adjPark(), r.adjPitcher(), r.adjWeatherHr(), condBoost, r.hrDistanceFt(),
            r.priceAmerican(), r.priceDecimal(), r.bestBook(), boomScore,
            buildReasons(r, coldGap, condBoost));
    }

    private static List<String> buildReasons(CandidateRow r, double coldGap, double condBoost) {
        List<String> reasons = new ArrayList<>();
        reasons.add(String.format(
            "Hitting %s and ice-cold — a last-30 xwOBA of %.3f against a %.3f season mark, "
            + "a %.0f-point slide the market and our own projection have already faded.",
            ordinal(r.lineupPosition()), r.xwobaL30(), r.xwoba(), coldGap * 1000));
        reasons.add(String.format(
            "The pop is still real: a %.1f%% barrel rate (%.1f× league) and a %.3f ISO — "
            + "bomb-tier raw power a cold streak doesn't erase.",
            r.barrelRate() * 100, r.barrelRate() / LEAGUE_BARREL_RATE, r.isoSeason()));
        reasons.add(String.format(
            "Today's setup leans his way against %s — park ×%.2f, pitcher ×%.2f, "
            + "weather ×%.2f on home runs (combined ×%.2f).",
            r.opposingPitcher(), r.adjPark(), r.adjPitcher(), r.adjWeatherHr(), condBoost));
        if (r.hrDistanceFt() != null) {
            reasons.add(String.format(
                "Projected to carry ~%.0f ft in this park and weather%s.",
                r.hrDistanceFt(), r.hrDistanceFt() >= LONG_BALL_FT ? " — top-tier distance" : ""));
        }
        reasons.add(
            "A pure-upside lotto: picked on power and matchup, not on price. High variance by "
            + "design — we grade it like any other pick so the record stays honest.");
        return reasons;
    }

    private static String ordinal(int n) {
        // 1st..9th batting order; the teens guard is harmless given the 1–9 domain.
        String suffix = (n % 100 >= 11 && n % 100 <= 13) ? "th"
            : switch (n % 10) {
                case 1 -> "st";
                case 2 -> "nd";
                case 3 -> "rd";
                default -> "th";
            };
        return n + suffix;
    }
}
