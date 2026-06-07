package com.diamond.api.auth;

import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Repository;

import java.sql.PreparedStatement;
import java.util.Optional;

/** User account lookups/inserts against {@code users} (auth MVP). */
@Repository
public class UserRepository {

    private final JdbcTemplate jdbc;

    public UserRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /** A full row including the bcrypt hash — never expose this outside auth. */
    public record UserRow(long id, String email, String handle, String passwordHash) {}

    private static final String SELECT = "SELECT id, email, handle, password_hash FROM users WHERE ";

    public Optional<UserRow> findByEmail(String email) {
        return one(SELECT + "email = ?", email);
    }

    public Optional<UserRow> findByHandle(String handle) {
        return one(SELECT + "handle = ?", handle);
    }

    private Optional<UserRow> one(String sql, String arg) {
        try {
            return Optional.ofNullable(jdbc.queryForObject(
                sql,
                (rs, n) -> new UserRow(
                    rs.getLong("id"),
                    rs.getString("email"),
                    rs.getString("handle"),
                    rs.getString("password_hash")),
                arg));
        } catch (EmptyResultDataAccessException e) {
            return Optional.empty();
        }
    }

    /** Inserts a new user and returns the generated id. */
    public long insert(String email, String handle, String passwordHash) {
        KeyHolder keys = new GeneratedKeyHolder();
        jdbc.update(con -> {
            PreparedStatement ps = con.prepareStatement(
                "INSERT INTO users (email, handle, password_hash) VALUES (?, ?, ?)",
                new String[] {"id"});
            ps.setString(1, email);
            ps.setString(2, handle);
            ps.setString(3, passwordHash);
            return ps;
        }, keys);
        Number id = keys.getKey();
        if (id == null) throw new IllegalStateException("INSERT did not return a generated id");
        return id.longValue();
    }
}
