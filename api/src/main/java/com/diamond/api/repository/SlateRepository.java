package com.diamond.api.repository;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.time.LocalDate;

/**
 * Resolves which slate the home board should show. The board used to scope to the raw
 * calendar date, so it flipped at midnight ET and dumped late-finishing games (and their
 * grades). Instead we hold the most recent slate that actually has games — which means
 * yesterday stays up overnight, then flips to today the moment the morning slate is pulled
 * (the ingester inserts today's {@code games} rows ~9am ET). The flip does not wait for
 * lineups or projections; those land later in the afternoon and populate the board in place.
 */
@Repository
public class SlateRepository {

    // Most recent game_date (on or before ET today) that has any games. Future dates can't
    // qualify because the ingester pulls only the current day's schedule, day-of.
    private static final String LATEST_WITH_GAMES_SQL = """
        SELECT MAX(g.game_date) FROM games g WHERE g.game_date <= ?
        """;

    private final JdbcTemplate jdbc;

    public SlateRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public LocalDate latestSlateWithGames(LocalDate etToday) {
        return jdbc.queryForObject(LATEST_WITH_GAMES_SQL, LocalDate.class, etToday);
    }
}
