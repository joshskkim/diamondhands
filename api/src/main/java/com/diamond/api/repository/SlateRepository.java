package com.diamond.api.repository;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.time.LocalDate;

/**
 * Resolves which slate the home board should show. The board used to scope to the raw
 * calendar date, so it flipped at midnight ET and dumped late-finishing games (and their
 * grades). Instead we hold the most recent slate that is actually "ready" — has at least
 * one game with a confirmed lineup AND a projection — so yesterday stays up overnight and
 * through the morning, then flips only once today's first lineup posts.
 */
@Repository
public class SlateRepository {

    // Most recent game_date (on or before ET today) with a confirmed 9-man lineup and a
    // batter projection on at least one game. The model projects same-day and lineups
    // confirm a few hours before first pitch, so a future date can't qualify early.
    private static final String LATEST_READY_SQL = """
        SELECT MAX(g.game_date)
        FROM games g
        WHERE g.game_date <= ?
          AND EXISTS (
              SELECT 1 FROM game_lineups gl
              WHERE gl.game_id = g.id
              GROUP BY gl.game_id HAVING COUNT(*) >= 9
          )
          AND EXISTS (
              SELECT 1 FROM batter_projections bp WHERE bp.game_id = g.id
          )
        """;

    // Fallback when nothing is "ready" yet (e.g. before the first lineup of the season):
    // the most recent date that has any games at all.
    private static final String LATEST_WITH_GAMES_SQL = """
        SELECT MAX(g.game_date) FROM games g WHERE g.game_date <= ?
        """;

    private final JdbcTemplate jdbc;

    public SlateRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public LocalDate latestReadySlate(LocalDate etToday) {
        return jdbc.queryForObject(LATEST_READY_SQL, LocalDate.class, etToday);
    }

    public LocalDate latestSlateWithGames(LocalDate etToday) {
        return jdbc.queryForObject(LATEST_WITH_GAMES_SQL, LocalDate.class, etToday);
    }
}
