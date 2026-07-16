# Ops cheat-sheet — day-2 box recall

Grab-and-go for "how do I get on the box / deploy / run the ingester again". Deliberately **no
hardcoded IP or secrets** (this repo is public) — instead these are the commands you run to
*retrieve* the values you need. Full first-time setup lives in [`deployment.md`](./deployment.md).

The box IP and creds are not in the repo on purpose. Get the IP from the Hetzner console (or ask
Claude — it's in project memory). Everything below assumes the app dir `/opt/diamond` and
`compose.prod.yml`.

## 1. Get on the box (stop re-asking this)

One-time: add an alias to `~/.ssh/config` on your Mac so it's `ssh diamond` forever after:

```
Host diamond
    HostName <box-ip>            # from Hetzner console / project memory
    User root
    IdentityFile ~/.ssh/diamond_deploy
```

Then just:

```bash
ssh diamond
cd /opt/diamond            # the app lives here; all commands below run from here
```

Raw form if the alias isn't set up: `ssh -i ~/.ssh/diamond_deploy root@<box-ip>`.

## 2. Recall the live values (run these on the box)

| Want to know… | Command |
|---|---|
| What's actually running / health | `docker compose -f compose.prod.yml ps` |
| Which image SHA each service is on | `docker compose -f compose.prod.yml images` |
| The deployed tag CD pinned | `grep IMAGE_TAG .env` |
| Fully-resolved config (env substituted) | `docker compose -f compose.prod.yml config` |
| A specific env var a service sees | `docker compose -f compose.prod.yml exec api env \| grep -i odds` |
| Query the DB | `docker compose -f compose.prod.yml exec -T postgres psql -U diamond -d diamond -c "<SQL>"` |
| Disk (the thing that crash-looped Postgres) | `df -h /` and `docker system df` |

## 3. Deploy

Deploys are **automatic on push to `main`** (GitHub Actions → GHCR → SSH). You usually don't
touch the box.

- **Re-run a deploy:** GitHub → Actions → latest **Deploy** run → *Re-run*.
- **Manual on-box equivalent** (rarely needed):
  ```bash
  cd /opt/diamond && git pull && docker compose -f compose.prod.yml pull \
    && docker compose -f compose.prod.yml up -d
  ```
- **Rollback to a previous build:**
  ```bash
  IMAGE_TAG=<previous-sha> docker compose -f compose.prod.yml up -d
  ```

## 4. Run an ingester one-shot

Use the helper (logs to `/var/log/diamond/`), not a raw `docker compose run`:

```bash
./deploy/run-ingester.sh smoke                 # read-only connectivity check
./deploy/run-ingester.sh daily                 # full nightly pipeline
./deploy/run-ingester.sh daily --quick         # afternoon lineups/odds loop
./deploy/run-ingester.sh refresh-odds --force  # force an odds pull
```

ℹ️ CD pins `IMAGE_TAG` to the deployed SHA in the box `.env`, so cron/one-shot ingester jobs
already run the **same** image as the long-running services — no longer a stale local `:latest`.
Manual fallback if you ever suspect a stale image:
`docker compose -f compose.prod.yml pull ingester`, then re-run.

## 5. Logs, restart, tunnels

```bash
docker compose -f compose.prod.yml logs -f api        # tail a service
docker compose -f compose.prod.yml restart api        # bounce a service
```

Observability (Grafana/Prometheus/Jaeger) is bound to `127.0.0.1` — reach it via SSH tunnel from
your Mac, then open the local ports in a browser:

```bash
ssh -L 3001:127.0.0.1:3001 -L 9090:127.0.0.1:9090 -L 16686:127.0.0.1:16686 diamond
```

## Gotchas worth remembering

- **TZ:** cron fires in the host clock. Box must be `America/New_York` or evening jobs shift ~4-5h.
- **Disk full → Postgres crash-loop:** if the API 500s and Postgres is stuck recovering, check
  `df -h /`; reclaim with `docker image prune -af` then restart postgres.
- **DB password** must be URL-safe hex (`openssl rand -hex 24`) — the ingester embeds it in a
  connection URL. Postgres bakes the password into its data volume on first init and **ignores**
  `POSTGRES_PASSWORD` after, so changing `DB_PASSWORD` in `.env` on a live box drifts it from the
  volume → `pg_isready` still passes but flyway fails auth and the app tier won't start. Deploy runs
  `./deploy/check-db-password.sh` as a preflight to catch this; run it by hand before rotating, and
  rotate on the **live volume** (`ALTER USER diamond WITH PASSWORD …`), not just in `.env`.
