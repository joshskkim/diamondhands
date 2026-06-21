# syntax=docker/dockerfile:1
# ── build ──────────────────────────────────────────────────────────────────────
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /build
# Resolve dependencies first (cached via BuildKit) so source-only changes are fast.
COPY pom.xml .
RUN --mount=type=cache,target=/root/.m2 mvn -B -ntp -q dependency:go-offline
COPY src ./src
# SENTRY_AUTH_TOKEN (optional BuildKit secret) activates the sentry-maven-plugin source-bundle
# upload during packaging. Absent (local/CI) → empty → the profile stays off, nothing uploads.
# The upload is best-effort: a Sentry/network hiccup (or a bad token) must never fail the image
# build, so if `package` fails with the profile active we retry once with it explicitly off.
# No `-q`, so the real Sentry error is visible in the build log when an upload does fail.
RUN --mount=type=cache,target=/root/.m2 \
    --mount=type=secret,id=sentry_auth_token,required=false \
    SENTRY_AUTH_TOKEN="$(cat /run/secrets/sentry_auth_token 2>/dev/null || true)" \
    sh -c 'mvn -B -ntp -DskipTests package \
      || { echo "WARN: build with Sentry source-bundle upload failed; retrying with upload disabled (non-fatal)"; \
           mvn -B -ntp -DskipTests -P "!sentry-source-context" package; }'

# ── runtime ────────────────────────────────────────────────────────────────────
FROM eclipse-temurin:21-jre AS runtime
WORKDIR /app
RUN groupadd -r app && useradd -r -g app app
COPY --from=build /build/target/diamond-api-*.jar /app/app.jar
USER app
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
