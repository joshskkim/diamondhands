package com.diamond.api.ai;

import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.api.Assertions.catchThrowableOfType;

class AgentRateLimiterTest {

    @Test
    void allowsUpToThePerMinuteLimitThen429s() {
        AgentRateLimiter limiter = new AgentRateLimiter(3, 100);
        limiter.check(1);
        limiter.check(1);
        limiter.check(1);
        ResponseStatusException ex = catchThrowableOfType(
            () -> limiter.check(1), ResponseStatusException.class);
        assertThat(ex.getStatusCode().value()).isEqualTo(429);
    }

    @Test
    void limitsArePerUser() {
        AgentRateLimiter limiter = new AgentRateLimiter(1, 100);
        limiter.check(1);
        // a different user is unaffected by user 1 hitting the limit
        limiter.check(2);
        assertThatThrownBy(() -> limiter.check(1)).isInstanceOf(ResponseStatusException.class);
    }

    @Test
    void dailyCapApplies() {
        AgentRateLimiter limiter = new AgentRateLimiter(100, 2);
        limiter.check(7);
        limiter.check(7);
        assertThatThrownBy(() -> limiter.check(7)).isInstanceOf(ResponseStatusException.class);
    }
}
