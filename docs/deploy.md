# Production deployment — MLB slate site

End-to-end hosting for the public MLB slate:

- **Vercel** — Next.js app in `web/` (Hobby tier)
- **Fly.io** — Python predictions API (`gametime.api.app`) with persistent volume
- **GitHub Actions** — optional daily `gametime-download` on the Fly volume (TASK-29)

Local Docker/Fly scaffolding lives in `Dockerfile`, `docker-compose.yml`, and `fly.toml` (TASK-28).

## Architecture

```text
User → https://<vercel-domain>/
     → Next.js /api/slate (server-side route handler)
     → https://<fly-app>.fly.dev/v1/slate
```

The browser only talks to Vercel. `GAMETIME_API_URL` is read on the **Next.js server** when proxying `/api/health` and `/api/slate` to Fly. CORS on the Python API is not required for the public site.

## Prerequisites

| Item | Notes |
|------|--------|
| [Fly.io](https://fly.io) account | `flyctl` installed locally |
| [Vercel](https://vercel.com) account | Hobby (free) sufficient for MVP |
| GitHub repo | For optional cron (TASK-29) and smoke workflow |
| Local `data/` + `models/mlb/pregame/` | From `gametime-download` + `gametime-pregame-train` for first volume seed |
| TASK-28 on `main` | `Dockerfile`, `fly.toml` at repo root (merged) |

## Volume layout (`GAMETIME_ROOT=/data`)

Paths in `configs/mlb.yaml` are relative to `GAMETIME_ROOT`. On Fly and in `docker-compose`, the persistent tree looks like:

```text
/data/
  configs/mlb.yaml              # YAML config (seed or bind-mount)
  data/mlb/processed/         # games.parquet + sidecars (gametime-download)
  data/mlb/raw/                 # download caches (optional on volume)
  models/mlb/pregame/           # ensemble.json, lgbm_*.txt, meta.json
```

The Docker image contains application code and default `configs/` under `/app/configs`, but **`GAMETIME_CONFIG=configs/mlb.yaml` resolves under `/data`**, so production config must exist on the volume (see seed steps below). Local `docker-compose` bind-mounts `./configs` → `/data/configs`.

## Local Docker (smoke before Fly)

**Prereqs:** host `data/` and `models/mlb/pregame/` populated (see [mlb_pregame_ops.md](mlb_pregame_ops.md)).

```bash
docker compose build api
docker compose up api
curl -s http://127.0.0.1:8000/health | python3 -m json.tool
```

Health endpoint: `GET /health` — returns `status`, `games_max_date`, `model_dir`, and `ensemble_members`.

**Web against local API:**

```bash
cd web
export GAMETIME_API_URL=http://127.0.0.1:8000
npm run dev
```

## Fly API deploy

`fly.toml` defaults (TASK-28):

| Setting | Value |
|---------|--------|
| `app` | `gametime-api` (rename before first deploy if taken) |
| `primary_region` | `sjc` |
| Volume `source` | `gametime_data` → `/data` |
| VM | shared-cpu-1x, 512mb (bump to 1gb if OOM during predictor init) |

### Step-by-step

1. Install [flyctl](https://fly.io/docs/hands-on/install-flyctl/) and log in.

2. Create the app (skip if `fly.toml` `app` already exists in your org):

```bash
fly apps create gametime-api
```

3. Create a volume in the **same region** as `primary_region` in `fly.toml`:

```bash
fly volumes create gametime_data --size 10 --region sjc
```

4. Validate config (optional):

```bash
fly config validate
```

5. Deploy:

```bash
fly deploy
```

6. **First-time volume seed** — after the first deploy, SSH in and populate config, data, and models:

```bash
# Copy configs from the image into the volume (volume mount hides /data from image layers)
fly ssh console -C "mkdir -p /data/configs && cp -r /app/configs/* /data/configs/"

# Download MLB processed data (pybaseball + Stats API; slow first run)
fly ssh console -C "pip install -e '/app[mlb]' && gametime-download --config /data/configs/mlb.yaml"
```

**Models** are not produced on every deploy. Copy artifacts from a local train (preferred):

```bash
# From dev machine — example using fly sftp (adjust app name)
fly sftp shell
# put -r models/mlb/pregame /data/models/mlb/pregame
```

Or train on the volume (slow; needs full download first):

```bash
fly ssh console -C "gametime-pregame-train --config /data/configs/mlb.yaml"
```

7. Verify:

```bash
curl -s https://gametime-api.fly.dev/health | python3 -m json.tool
```

Replace `gametime-api` with your Fly app name. Expect `games_max_date` ≥ yesterday after a successful download.

### Sizing

`fly.toml` starts at **shared-cpu-1x / 512mb**. LightGBM + 13-member ensemble load can OOM at 512mb; set `memory = "1gb"` under `[vm]` if the machine restarts during predictor init.

## Vercel frontend deploy

1. Import the GitHub repo in the [Vercel dashboard](https://vercel.com/new).
2. Set **Root Directory** to `web` (monorepo setting).
3. Framework preset: **Next.js** (auto-detected). Build command: `npm run build`. Output: Next.js default.
4. Add **Production** environment variable:

| Variable | Example | Purpose |
|----------|---------|---------|
| `GAMETIME_API_URL` | `https://gametime-api.fly.dev` | Server-side BFF proxy → Fly API |

Do **not** set `NEXT_PUBLIC_API_URL` to the Fly URL for browser direct calls — the slate uses same-origin `/api/*` routes only.

5. Deploy. Open the production URL and confirm the slate loads (use `/?date=YYYY-MM-DD` for a historical date if today's slate is empty).

`web/vercel.json` pins the Next.js framework preset; root directory `web` is configured in the Vercel project settings.

## Secrets and environment variables

| Secret / variable | Where | Purpose |
|-------------------|-------|---------|
| `FLY_API_TOKEN` | GitHub Actions secrets | TASK-29 cron (`fly ssh console`) |
| `GAMETIME_API_URL` | Vercel (Production) | BFF → Fly HTTPS URL |
| `FLY_APP_URL` | GitHub Actions secrets (optional) | Deploy smoke — `https://<app>.fly.dev` |
| `VERCEL_PRODUCTION_URL` | GitHub Actions secrets (optional) | Deploy smoke — production site URL |

### Create `FLY_API_TOKEN` (TASK-29 cron)

```bash
fly tokens create deploy -x 999999h
```

Add the token as `FLY_API_TOKEN` in **GitHub → Settings → Secrets and variables → Actions**.

## Daily data refresh (TASK-29)

GitHub Actions runs `gametime-download` **on the Fly volume** so `games.parquet` stays current:

```text
GitHub Actions (cron 0 14 * * * UTC)
  → flyctl ssh console -a gametime-api -C "pip install ... && gametime-download ..."
```

Workflow: `.github/workflows/mlb-data-refresh.yml`

| Setting | Value |
|---------|--------|
| Schedule | `0 14 * * *` (14:00 UTC daily — after most US overnight finals) |
| Manual | `workflow_dispatch` |
| `FLY_APP` | Workflow env, default `gametime-api` (must match `fly.toml` `app`) |
| Secret | `FLY_API_TOKEN` (required) |

Remote command (paths match TASK-28 volume layout):

```bash
pip install -q -e '/app[mlb]' \
  && gametime-download --config /data/configs/mlb.yaml
```

`/app` is the Docker image; `/data` is the mounted volume (`GAMETIME_ROOT=/data`). Config and parquet paths resolve under `/data`.

**Manual trigger (GitHub CLI):**

```bash
gh workflow run mlb-data-refresh.yml
```

Or **Actions → MLB data refresh → Run workflow** in the GitHub UI.

**Success check:** `curl https://<app>.fly.dev/health` → `games_max_date` ≥ yesterday (US game calendar). The workflow logs `games_max_date` from parquet after download.

**Fallback** if `fly ssh` is unavailable: SSH manually and run the same download command:

```bash
fly ssh console -a gametime-api -C "pip install -q -e '/app[mlb]' && gametime-download --config /data/configs/mlb.yaml"
```

Until cron is enabled, re-run download via `fly ssh console` or the workflow manually after games complete. Ensemble retrain is **not** on schedule — trigger `gametime-pregame-train` manually when members change.

## Optional deploy smoke workflow

`.github/workflows/deploy-smoke.yml` — `workflow_dispatch` only.

Curls Fly `/health` and the Vercel homepage when secrets are set. Skips gracefully if `FLY_APP_URL` or `VERCEL_PRODUCTION_URL` are missing.

```bash
gh workflow run deploy-smoke.yml
```

## Alternates (not recommended for MVP)

| Option | Tradeoff |
|--------|----------|
| Vercel serverless for Python API | Cold start + large ML deps; not suitable for LightGBM ensemble |
| [Render](https://render.com) free tier | Service sleeps; cold start on first request |
| Oracle / generic VM | Full control; you manage OS, TLS, and volume backups |

## Cost notes

| Layer | MVP expectation |
|-------|-----------------|
| Vercel Hobby | Free for personal/small traffic |
| Fly.io | Free allowance covers light use; **10GB volume + always-on shared VM** may exceed free tier at scale |
| GitHub Actions | Cron minutes within free tier for one daily job |

Monitor Fly billing after enabling `min_machines_running = 1`.

## Troubleshooting

| Symptom | Check |
|---------|--------|
| Fly machine restarts on boot | OOM — bump `[vm] memory` to `1gb` in `fly.toml` and redeploy |
| Slate empty or stale | `games_max_date` in `/health`; run TASK-29 cron or manual `gametime-download` |
| Vercel 502 on `/api/slate` | `GAMETIME_API_URL` set to `https://<app>.fly.dev` (HTTPS); Fly app healthy |
| `ensemble_members` empty in health | Models missing on volume — seed `models/mlb/pregame/` |
| Browser CORS errors | Client should call `/api/slate`, not Fly directly — fix any `NEXT_PUBLIC_API_URL` misuse |

## Related

- [mlb_pregame_ops.md](mlb_pregame_ops.md) — download, train, local API
- `Dockerfile`, `docker-compose.yml`, `fly.toml` at repo root (TASK-28)
- `web/README.md` — BFF env vars for Next.js
