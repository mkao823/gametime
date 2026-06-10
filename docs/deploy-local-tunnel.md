# Local API + Cloudflare Tunnel (free MVP)

Run the predictions API on your machine with Docker, expose it over HTTPS via [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) (no router port forwarding), and point the Vercel frontend at the tunnel URL.

| Layer | Provider | Notes |
|-------|----------|-------|
| Frontend | **Vercel** Hobby | `web/` — unchanged |
| API | **Local Docker** | `docker-compose.yml` — bind-mount `./data`, `./models` |
| Public HTTPS | **Cloudflare Tunnel** | `cloudflared` → `http://127.0.0.1:8000` |
| Data refresh | **Local cron** or manual | `gametime-download` on the host (not inside the container) |

```text
User → https://<vercel-domain>/
     → Next.js /api/slate (server)
     → https://<tunnel-hostname>/v1/slate
          ↑ cloudflared on local machine
          ↑ docker compose api :8000
```

The browser only talks to Vercel. `GAMETIME_API_URL` is read on the **Next.js server** when proxying `/api/health` and `/api/slate`. CORS on the Python API is not required for the public site.

For paid cloud hosting (Fly.io volume + GitHub Actions cron), see [deploy.md — Alternate: Fly.io](deploy.md#alternate-flyio-paid).

---

## Prerequisites

| Item | Notes |
|------|--------|
| [Docker](https://docs.docker.com/get-docker/) | Desktop or Engine + Compose v2 |
| Python ≥3.9 + MLB extras | `pip install -e '.[mlb]'` on the **host** for download/train |
| Seeded `data/` + `models/` | See [mlb_pregame_ops.md](mlb_pregame_ops.md) |
| [Cloudflare](https://dash.cloudflare.com/sign-up) account | Free tier is sufficient |
| `cloudflared` CLI | [Install guide](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) |
| [Vercel](https://vercel.com) account | Hobby (free) for `web/` |

### Seed data and models (one-time)

From the repo root:

```bash
pip install -e '.[mlb]'
gametime-download --config configs/mlb.yaml
gametime-pregame-train --config configs/mlb.yaml   # if models/mlb/pregame/ is empty
```

Confirm processed games include yesterday:

```bash
python3 -c "
import pandas as pd
g = pd.read_parquet('data/mlb/processed/games.parquet')
g['game_date'] = pd.to_datetime(g['game_date'])
print('max_date', g['game_date'].max().date())
"
```

---

## Start the API (Docker)

`docker-compose.yml` bind-mounts host paths into the container (`GAMETIME_ROOT=/data`):

```text
./configs  → /data/configs
./data     → /data/data
./models   → /data/models
```

Build and start (detached):

```bash
docker compose build api
docker compose up -d api
```

Or use the helper script:

```bash
./scripts/local-api-up.sh
```

Verify locally:

```bash
curl -s http://127.0.0.1:8000/health | python3 -m json.tool
```

`GET /health` returns `status`, `games_max_date`, `model_dir`, and `ensemble_members`. Expect `games_max_date` ≥ yesterday after a successful download.

**Web against local API (no tunnel):**

```bash
cd web
export GAMETIME_API_URL=http://127.0.0.1:8000
npm run dev
```

---

## Cloudflare Tunnel

Install `cloudflared` and log in once:

```bash
cloudflared tunnel login
```

Choose the quick tunnel for dev smoke tests, or a **named tunnel** for a stable hostname in production.

### Quick tunnel (dev / smoke)

No DNS setup. URL changes each time you restart the tunnel.

```bash
cloudflared tunnel --url http://127.0.0.1:8000
```

Copy the `https://*.trycloudflare.com` URL from the log output. Use it as `GAMETIME_API_URL` on Vercel for a short-lived test.

Verify:

```bash
curl -s https://<random>.trycloudflare.com/health | python3 -m json.tool
```

### Named tunnel (stable URL)

Use a hostname you control, e.g. `api.example.com`.

#### 1. Create the tunnel

In the [Cloudflare Zero Trust dashboard](https://one.dash.cloudflare.com/) → **Networks** → **Tunnels** → **Create a tunnel**, or via CLI:

```bash
cloudflared tunnel create gametime-api
```

This prints a **tunnel UUID** and writes a credentials JSON file, typically:

```text
~/.cloudflared/<TUNNEL_UUID>.json
```

Keep that JSON **private** — it is the tunnel token. Do not commit it to Git.

#### 2. Route DNS

In the tunnel setup UI (or **Public Hostname** tab), add a route:

| Field | Example |
|-------|---------|
| Subdomain | `api` |
| Domain | `example.com` |
| Service | `http://127.0.0.1:8000` |

Or create a CNAME manually: `api.example.com` → `<TUNNEL_UUID>.cfargotunnel.com`.

#### 3. Config file

Copy the example and edit paths/hostname:

```bash
cp config/cloudflared.yml.example ~/.cloudflared/config.yml
# edit tunnel UUID, credentials path, and hostname
```

Example (`config/cloudflared.yml.example`):

```yaml
tunnel: <TUNNEL_UUID>
credentials-file: /path/to/<TUNNEL_UUID>.json

ingress:
  - hostname: api.example.com
    service: http://127.0.0.1:8000
  - service: http_status:404
```

Run the tunnel:

```bash
cloudflared tunnel --config ~/.cloudflared/config.yml run
```

Or adapt `scripts/cloudflared-run.sh.example` for your paths.

Verify:

```bash
curl -s https://api.example.com/health | python3 -m json.tool
```

#### 4. Run on boot (optional)

**macOS (launchd):** create `~/Library/LaunchAgents/com.gametime.cloudflared.plist` pointing at `cloudflared tunnel run` with your config. Load with `launchctl load`.

**Linux (systemd):** unit file running `cloudflared tunnel --config /path/to/config.yml run` as your user; `systemctl enable --now cloudflared`.

These are operator-specific — treat the snippets above as patterns, not shipped repo services.

---

## Vercel wiring

1. Import the GitHub repo in the [Vercel dashboard](https://vercel.com/new).
2. Set **Root Directory** to `web`.
3. Add **Production** environment variable:

| Variable | Example |
|----------|---------|
| `GAMETIME_API_URL` | `https://api.example.com` (named tunnel) or `https://<random>.trycloudflare.com` (dev) |

Do **not** set `NEXT_PUBLIC_API_URL` to the tunnel URL — the browser uses same-origin `/api/*` routes only.

4. Redeploy after changing env vars.

See also [web/README.md](../web/README.md).

---

## Verify end-to-end

1. Docker API healthy: `curl http://127.0.0.1:8000/health`
2. Tunnel healthy: `curl https://<tunnel-hostname>/health` → `games_max_date` present
3. Vercel site loads; open `/?date=YYYY-MM-DD` for a historical slate if today is empty
4. Vercel `/api/health` returns the same `games_max_date` as the tunnel (BFF proxy)

---

## Daily data refresh (local cron)

Run `gametime-download` on the **host**, not inside the API container. The container reads bind-mounted `./data` on the next request.

Example crontab (14:00 UTC daily — after most US overnight finals):

```cron
0 14 * * * cd /path/to/gametime && /path/to/.venv/bin/gametime-download --config configs/mlb.yaml >> /tmp/gametime-download.log 2>&1
```

Adjust paths to your checkout and virtualenv. Use `crontab -e` to install.

**Success check:** after the job runs, `curl http://127.0.0.1:8000/health` → `games_max_date` ≥ yesterday.

Ensemble retrain is **not** on schedule — run `gametime-pregame-train` manually when members change.

The GitHub Actions workflow `.github/workflows/mlb-data-refresh.yml` (TASK-29) targets **Fly.io** only; it is **not used** for this local-tunnel MVP.

---

## Keep-alive and uptime

| Risk | Mitigation |
|------|------------|
| Laptop sleep / lid closed | API and tunnel stop; use a desktop or server that stays awake |
| Power loss | Site goes down until machine and tunnel restart |
| Tunnel process exit | Use launchd/systemd or a process manager |
| Docker not running | Start Docker Desktop or enable `docker` service on boot |

This path is **single-machine, single-region** — fine for a personal MVP, not HA production.

---

## Limitations

- Home network uptime depends on your machine staying on.
- Quick tunnel URLs are ephemeral and unsuitable for production.
- Named tunnel credentials (`*.json`) are secrets — store under `~/.cloudflared/`, never in the repo.
- No multi-region failover; Vercel still serves the frontend if the tunnel is down, but `/api/slate` will 502.
- Download cron on the host requires Python + `pip install -e '.[mlb]'` outside Docker.

---

## Troubleshooting

| Symptom | Check |
|---------|--------|
| `connection refused` on tunnel URL | `docker compose ps` — is `api` running? `curl localhost:8000/health` |
| Vercel 502 on `/api/slate` | `GAMETIME_API_URL` is HTTPS tunnel URL; tunnel process running |
| Stale slate / old `games_max_date` | Run `gametime-download` on host; confirm parquet `max_date` |
| `ensemble_members` empty | Run `gametime-pregame-train`; check `models/mlb/pregame/` on host |
| Tunnel auth errors | Re-run `cloudflared tunnel login`; verify credentials JSON path |
| Browser CORS errors | Client should call `/api/slate`, not the tunnel directly |

---

## Related

- [deploy.md](deploy.md) — overview; Fly.io alternate path
- [mlb_pregame_ops.md](mlb_pregame_ops.md) — download, train, local API
- `docker-compose.yml`, `Dockerfile` at repo root (TASK-28)
- `config/cloudflared.yml.example` — named tunnel template
