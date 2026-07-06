package com.diamond.api.config;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/**
 * The global error contract: ResponseStatusException keeps its status and exposes its reason;
 * unexpected exceptions become a generic 500 (no internals leaked); Spring MVC's own binding
 * errors keep their standard 400 instead of falling into the catch-all.
 */
class ApiExceptionHandlerTest {

    @RestController
    static class ThrowingController {
        @GetMapping("/boom/rse")
        void rse() { throw new ResponseStatusException(HttpStatus.NOT_FOUND, "no pick today"); }

        @GetMapping("/boom/unexpected")
        void unexpected() { throw new IllegalStateException("db exploded: password=hunter2"); }

        @GetMapping("/boom/typed")
        void typed(@RequestParam int n) { }
    }

    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        mvc = MockMvcBuilders.standaloneSetup(new ThrowingController())
            .setControllerAdvice(new ApiExceptionHandler())
            .build();
    }

    @Test
    void responseStatusException_keepsStatusAndReason() throws Exception {
        mvc.perform(get("/boom/rse"))
            .andExpect(status().isNotFound())
            .andExpect(jsonPath("$.status").value(404))
            .andExpect(jsonPath("$.error").value("Not Found"))
            .andExpect(jsonPath("$.message").value("no pick today"))
            .andExpect(jsonPath("$.path").value("/boom/rse"));
    }

    @Test
    void unexpectedException_isGeneric500_withoutLeakingInternals() throws Exception {
        mvc.perform(get("/boom/unexpected"))
            .andExpect(status().isInternalServerError())
            .andExpect(jsonPath("$.status").value(500))
            .andExpect(jsonPath("$.message").value("Something went wrong handling this request."));
    }

    @Test
    void springBindingErrors_keepTheir400() throws Exception {
        mvc.perform(get("/boom/typed").param("n", "not-a-number"))
            .andExpect(status().isBadRequest());
    }
}
