# syntax=docker/dockerfile:1
# ── build ──────────────────────────────────────────────────────────────────────
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /build
# Resolve dependencies first (cached via BuildKit) so source-only changes are fast.
COPY pom.xml .
RUN --mount=type=cache,target=/root/.m2 mvn -B -ntp -q dependency:go-offline
COPY src ./src
RUN --mount=type=cache,target=/root/.m2 mvn -B -ntp -q -DskipTests package

# ── runtime ────────────────────────────────────────────────────────────────────
FROM eclipse-temurin:21-jre AS runtime
WORKDIR /app
RUN groupadd -r app && useradd -r -g app app
COPY --from=build /build/target/diamond-api-*.jar /app/app.jar
USER app
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
