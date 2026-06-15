# Release checklist

Go/no-go for the first official deployment (and a sanity pass for later ones).
Full how-to lives in [`deployment.md`](./deployment.md); this is the gate.

## Pre-flight (before flipping CD on)
- [ ] **VPS** reachable; Docker Engine + Compose plugin installed (`docker compose version`).
- [ ] **DNS** `A` record resolves to the VPS IP (`dig +short your-domain.com`). Cloudflare proxy **off** (grey cloud).
- [ ] **Deploy key** authorized on the box; you can `ssh -i diamond_deploy user@VPS_IP` non-interactively.
- [ ] **`/opt/diamond/.env`** filled: `DOMAIN`, `DB_PASSWORD`, `AUTH_JWT_SECRET` (≥32 bytes), `GRAFANA_ADMIN_PASSWORD`, `ODDS_API_KEY` (optional), `ACME_EMAIL` (optional).
- [ ] **GHCR access**: the three `diamond-*` packages are public, or the box has `docker login ghcr.io`.
- [ ] **CI green on `main`** — `API CI` passing (Flyway-from-scratch + tests). Branch protection on `main` requires it.

## First bring-up (on the box)
- [ ] `docker compose -f compose.prod.yml up -d` — Flyway migrates, then api/web/caddy start.
- [ ] TLS issued: `https://your-domain.com/` loads over a valid cert (not the internal CA).
- [ ] Seed data: `ingester load-static` → `backfill-stats` (slow) → `daily`.
- [ ] `https://your-domain.com/api/games/today` returns JSON.
- [ ] Sign-up / sign-in works (httpOnly `diamond_session` cookie set, `Secure`).
- [ ] Cron installed (`crontab deploy/crontab.example`, paths/TZ edited).

## Turn on CD
- [ ] GitHub secrets set: `SSH_HOST`, `SSH_USER`, `SSH_KEY`.
- [ ] GitHub variable set: `DOMAIN` (un-gates the `deploy` job).
- [ ] Push to `main` (or re-run **Deploy**) → build → deploy → **smoke test passes** (green).

## Operability
- [ ] Observability reachable via SSH tunnel (Grafana :3001, Prometheus :9090, Jaeger :16686).
- [ ] Backups: `deploy/backup.sh` runs via cron; confirm a `.sql.gz` lands in `DIAMOND_BACKUP_DIR`. Consider syncing offsite.
- [ ] **Rollback rehearsed**: `IMAGE_TAG=<previous-sha> docker compose -f compose.prod.yml up -d` brings the prior build back.

## Notes
- Smoke test only confirms the site answers; it is not a functional test suite.
- After any schema change, the from-scratch Flyway check in `API CI` is the guard — keep it required.
