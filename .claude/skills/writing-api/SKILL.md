---
name: writing-api
description: Conventions for the Java Spring Boot API (api/). Read before adding or editing controllers, services, repositories, or DTOs under api/.
---

# Writing api/ code

Stack: Java 21, Spring Boot, hand-written `JdbcTemplate` SQL (deliberately no JPA), Redis caching.
Local builds: `export JAVA_HOME=/opt/homebrew/opt/openjdk@21` first — the machine default (17)
makes Mockito fail cryptically.

## Layering

`controller/` (thin HTTP mapping) → `service/` (logic + caching) → `repository/` (SQL + row
mapping) → `dto/` (Java **records** only). Feature slices (`ai/`, `auth/`, `billing/`) keep the
same shape internally. A new endpoint = new method through all three layers, not logic in the
controller.

## Repositories

- Hand-tuned SQL is a feature here, but **batch it**: one query for N players, never a per-row
  loop (`RepositoryBatchEquivalenceTest` documents why).
- Before writing a new slate/lineup/game_odds join, check
  `PropBoardRepository` / `MostLikelyRepository` / `LottoRepository` — reuse their shared SQL
  fragments (consolidation in progress) instead of hand-copying the join.
- Queries against `pitcher_arsenal` / `batter_pitch_type_stats` MUST filter season — those tables
  hold multiple seasons at the same `as_of_date` and rows fan out silently.
- Mapper naming: `toDto` (one convention — not `map*`/`build*`).

## Services

- Caching: `@Cacheable(cacheNames = "…")` with a named cache; all caches share one 5-minute Redis
  TTL. `RedisConfig` throws on cached nulls — use `unless = "#result == null"` for nullable
  results (204-style endpoints).
- Odds math (american↔decimal, implied prob, de-vig) lives in ONE util (`OddsMath` — being
  consolidated from `OddsModel`/`KellyCalculator`/inline `fairShare`). Never re-derive it inline.
- Multi-statement write paths get `@Transactional`.

## Errors

Errors go through the global `@RestControllerAdvice` handler with the shared error-body record
(being introduced in cleanup) — no ad-hoc `ResponseStatusException` message strings scattered in
controllers.

## Done =

`mvn -B -ntp verify` green (CI also applies Flyway from scratch — never renumber or edit an
existing migration; check the shared dev DB's flyway history before numbering a new one).
Every new service gets a unit test (Mockito, see `LottoServiceTest` for the current shape).
