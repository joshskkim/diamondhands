package com.diamond.api.repository;

import com.diamond.api.dto.PitcherSkillDto;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.util.List;

/** Season-level pitcher skill lookups from {@code pitcher_skill}. */
@Repository
public class PitcherRepository {

    private final JdbcTemplate jdbc;

    public PitcherRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    // One row per vs_handedness for the pitcher's latest available season.
    private static final String SKILL_SQL = """
        SELECT vs_handedness, k_rate, bb_rate, xwoba_against, hr_per_pa, batters_faced
        FROM pitcher_skill
        WHERE player_id = ?
          AND season = (SELECT MAX(season) FROM pitcher_skill WHERE player_id = ?)
        ORDER BY vs_handedness
        """;

    public List<PitcherSkillDto> skill(int pitcherId) {
        return jdbc.query(
            SKILL_SQL,
            (rs, n) -> new PitcherSkillDto(
                rs.getString("vs_handedness"),
                toDouble(rs.getBigDecimal("k_rate")),
                toDouble(rs.getBigDecimal("bb_rate")),
                toDouble(rs.getBigDecimal("xwoba_against")),
                toDouble(rs.getBigDecimal("hr_per_pa")),
                (Integer) rs.getObject("batters_faced")),
            pitcherId, pitcherId);
    }

    private static Double toDouble(BigDecimal bd) {
        return bd == null ? null : bd.doubleValue();
    }
}
