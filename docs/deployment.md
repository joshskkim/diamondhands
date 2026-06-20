# Deployment runbook — single VPS, Docker Compose

The whole app runs on one Linux box via `compose.prod.yml`, fronted by **Caddy**
(auto-TLS, same-origin routing). CD is GitHub Actions → GHCR → SSH.

```
Internet :443 → Caddy ─ /api/* → api:8080 (Spring Boot)
                       ─ /*     → web:3000 (Next.js standalone)
host cron → docker compose run ingester (one-shot jobs)
postgres + redis + prometheus/grafana/jaeger  (internal; observability bound to 127.0.0.1)
```

Why same-origin: web and API share one public origin, so the httpOnly `diamond_session`
cookie works with `SameSite=Lax` + `Secure` and **CORS is unused** in prod. (If you ever move to
`app.` / `api.` subdomains, parametrize `CorsConfig` and switch the cookie to `SameSite=None`.)

## First release — from zero

Walk this top to bottom once. Steps 1–4 are operational (you do them); step 5
wires CD; step 6 ships. See `docs/RELEASE.md` for the go/no-go checklist.

### 1. Get a VPS
Any Linux box with Docker works. Recommended: **Hetzner Cloud CPX21** (~€8/mo,
3 vCPU / 4 GB) or a DigitalOcean / Vultr equivalent (2 vCPU / 4 GB is plenty).
Ubuntu 24.04, then install Docker Engine + the Compose plugin:
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER" && newgrp docker   # run docker without sudo
```

### 2. Domain + DNS
Register a domain (Cloudflare, Namecheap, …) and add a single `A` record for the
apex (or a subdomain) pointing at the VPS IP. Verify it resolves before
deploying — Let's Encrypt's HTTP-01 challenge needs it:
```bash
dig +short your-domain.com    # should print the VPS IP
```
> Using Cloudflare? Keep the record **DNS-only (grey cloud)**, not proxied —
> the orange-cloud proxy breaks Caddy's ACME challenge on first issuance.

### 3. CD deploy key
Generate a dedicated keypair for GitHub Actions (no passphrase) and authorize it
on the box:
```bash
ssh-keygen -t ed25519 -f ./diamond_deploy -N "" -C "github-actions-deploy"
ssh-copy-id -i ./diamond_deploy.pub user@VPS_IP      # or append .pub to ~/.ssh/authorized_keys
```
The **private** key (`diamond_deploy`) becomes the `SSH_KEY` secret in step 5.

### 4. Provision the app on the box
```bash
sudo mkdir -p /opt/diamond && sudo chown "$USER" /opt/diamond
git clone https://github.com/joshskkim/diamondhands /opt/diamond && cd /opt/diamond
cp .env.prod.example .env    # fill DOMAIN, DB_PASSWORD, AUTH_JWT_SECRET, GRAFANA_…, ODDS_API_KEY, ACME_EMAIL
```
**GHCR access (easy to miss):** the images are private by default, so the box
must authenticate before `compose pull` can fetch them — otherwise the *next*
deploy fails with `denied`/`manifest unknown` even after SSH works. Either:
- make the three `diamond-*` packages public (GitHub → your packages → Package
  settings → Change visibility), **or**
- log in once on the box with a `read:packages` PAT:
  ```bash
  echo "$GHCR_PAT" | docker login ghcr.io -u joshskkim --password-stdin
  ```
Then bring it up and seed (see the detailed commands under *One-time
provisioning* below), and install the cron schedule.

### 5. Wire CD (GitHub → Settings → Secrets and variables → Actions)
- **Secrets:** `SSH_HOST` (VPS IP), `SSH_USER`, `SSH_KEY` (the private key from
  step 3).
- **Variable:** `DOMAIN` (your domain). This both un-gates the `deploy` job and
  is baked into the web image at build time.

The `deploy` job is gated on `vars.DOMAIN` — until you set it the job **skips**
(CD stays green) instead of failing. Once set, every push to `main` builds →
pushes to GHCR → SSH-deploys → **smoke-tests** `https://DOMAIN/` and
`/api/games/today`, failing the run (with the last 80 lines of `api`/`web` logs)
if the site doesn't answer.

### 6. Ship
Push to `main` (or re-run the latest **Deploy** run from the Actions tab). Watch
it go green through the smoke test, then load `https://your-domain.com`.

---

## Prerequisites
- A Linux VPS (2 vCPU / 4 GB is plenty), Docker Engine + Compose plugin.
- A domain with an `A` record → the VPS IP (needed for Let's Encrypt).

## One-time provisioning
```bash
# on the VPS
sudo mkdir -p /opt/diamond && sudo chown "$USER" /opt/diamond
git clone https://github.com/joshskkim/diamondhands /opt/diamond
cd /opt/diamond

cp .env.prod.example .env       # then edit:
#   DOMAIN=your-domain.com
#   DB_PASSWORD=$(openssl rand -base64 24)
#   AUTH_JWT_SECRET=$(openssl rand -base64 48)
#   GRAFANA_ADMIN_PASSWORD=...   ODDS_API_KEY=...   (REGISTRY/IMAGE_TAG defaults are fine)
#   GEMINI_API_KEY=...  AI_ENABLED=true   (optional — turns on the Ask Diamond AI search)

# GHCR images are private by default — log in once (read:packages PAT), or make the
# packages public and skip this:
echo "$GHCR_PAT" | docker login ghcr.io -u joshskkim --password-stdin

docker compose -f compose.prod.yml up -d        # flyway migrates, then api/web/caddy start
```
First-time data seeding (one-time, then the nightly cron keeps it fresh):
```bash
docker compose -f compose.prod.yml run --rm ingester load-static
docker compose -f compose.prod.yml run --rm ingester backfill-stats     # slow first run
docker compose -f compose.prod.yml run --rm ingester daily              # today's slate
```
Install the schedule (edit paths/TZ first):
```bash
crontab deploy/crontab.example     # morning daily + */30 quick loop + tennis + weekly prior refresh + nightly backup
```

## Ask Diamond AI (optional)
The ⌘K "Ask Diamond" search needs a Gemini key. It's read **only** from the `GEMINI_API_KEY`
env var (`app.ai.api-key` in `application.yml`) and is never committed — with `AI_ENABLED` unset the
`/api/ask` endpoint stays dark (503), so the key is purely opt-in.
- **Prod:** put `GEMINI_API_KEY` + `AI_ENABLED=true` in the host `.env` (gitignored), same as the
  other secrets. Optionally `AI_MODEL=gemini-2.5-pro` to trade cost for quality.
- **Local dev:** don't hardcode it. Either `export GEMINI_API_KEY=… AI_ENABLED=true` before
  `mvn spring-boot:run`, or keep it in a gitignored `api/.env.local` and source it:
  `set -a; source api/.env.local; set +a; mvn spring-boot:run`.

## Alerting (optional)
Prometheus alerts (`ApiDown`, 5xx>5%, latency, HikariCP saturation) are routed to **Alertmanager**,
which emails them. It's opt-in and commits no secrets:
- Set `ALERT_SMTP_SMARTHOST` (e.g. `smtp.gmail.com:587`), `ALERT_SMTP_FROM`, `ALERT_SMTP_TO`,
  `ALERT_SMTP_USERNAME`, `ALERT_SMTP_PASSWORD` in the host `.env`. For Gmail use a 16-char App
  Password. Leave `ALERT_SMTP_SMARTHOST` blank to disable (Alertmanager starts with a null receiver).
- Reach the Alertmanager UI via SSH tunnel (`127.0.0.1:9093`), like Grafana/Prometheus/Jaeger.
- Test it: `docker compose -f compose.prod.yml stop api`, wait ~2m → an `ApiDown` email; `start` to resolve.

## CD setup (GitHub)
- Repo **variable** `DOMAIN` = your domain (baked into the web image at build time). The `deploy`
  job is **gated on `DOMAIN`** — unset → the job skips (CD stays green) instead of failing.
- Repo **secrets**: `SSH_HOST`, `SSH_USER`, `SSH_KEY` (a deploy key the box authorizes).
- Enable **branch protection** on `main` requiring the **API CI** check — that's the test gate;
  `deploy.yml` then runs on every push to `main`: build 3 images → push to GHCR (tagged by SHA +
  `latest`) → SSH in and `git pull && compose pull && compose up -d` (pinned to the new SHA) →
  **smoke-test** `https://DOMAIN/` and `/api/games/today` (fails the run + dumps `api`/`web` logs
  if the site doesn't come up). The `deploy` job runs under the `production` environment.

## Operations
```bash
docker compose -f compose.prod.yml ps                 # status
docker compose -f compose.prod.yml logs -f api        # tail a service
docker compose -f compose.prod.yml run --rm ingester smoke   # read-only DB check
```
Observability is bound to `127.0.0.1` — reach it through an SSH tunnel:
```bash
ssh -L 3001:127.0.0.1:3001 -L 9090:127.0.0.1:9090 -L 16686:127.0.0.1:16686 user@vps
# → Grafana http://localhost:3001, Prometheus :9090, Jaeger :16686
```

## Rollback
Every build is tagged by commit SHA, so roll back by pinning the previous tag:
```bash
IMAGE_TAG=<previous-sha> docker compose -f compose.prod.yml up -d
```

## Backups & restore
`deploy/backup.sh` (nightly cron) writes `pg_dump` gzips to `DIAMOND_BACKUP_DIR` with
`DIAMOND_BACKUP_RETAIN_DAYS` retention. For real durability, sync that dir offsite (e.g. rclone to
object storage). Restore:
```bash
gunzip -c backups/diamond-YYYYmmdd-HHMMSS.sql.gz \
  | docker compose -f compose.prod.yml exec -T postgres psql -U diamond -d diamond
```

## Secrets
Nothing secret is committed — `.env` (root and `ingester/`) is gitignored. The Odds API key has
**never** been in git history; if it is ever exposed, rotate it in The Odds API dashboard. Prod
values live only in the host `.env` and in GitHub Actions secrets.
