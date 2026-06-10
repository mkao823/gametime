# Deployment — MLB predictions API

Container and Fly.io scaffolding for the read-only FastAPI service (`gametime.api.app`). Vercel web wiring is completed in TASK-30.

## Volume layout (`GAMETIME_ROOT=/data`)

Paths in `configs/mlb.yaml` are relative to `GAMETIME_ROOT`. On Fly and in `docker-compose`, the persistent tree looks like:

```text
/data/
  configs/mlb.yaml              # YAML config (seed or bind-mount)
  data/mlb/processed/           # games.parquet + sidecars (gametime-download)
  data/mlb/raw/                 # download caches (optional on volume)
  models/mlb/pregame/           # ensemble.json, lgbm_*.txt, meta.json
```

The Docker image contains application code and default `configs/` under `/app/configs`, but **`GAMETIME_CONFIG=configs/mlb.yaml` resolves under `/data`**, so production config must exist on the volume (see seed steps below). Local `docker-compose` bind-mounts `./configs` → `/data/configs`.

## Local Docker

**Prereqs:** host `data/` and `models/mlb/pregame/` populated (see [mlb_pregame_ops.md](mlb_pregame_ops.md)).

```bash
docker compose build api
docker compose up api
curl -s http://127.0.0.1:8000/health | python3 -m json.tool
```

Health endpoint: `GET /health` — returns `status`, `games_max_date`, `model_dir`, and `ensemble_members`.

**Web:** run the Next.js app on the host with `GAMETIME_API_URL=http://127.0.0.1:8000` (Vercel deploy in TASK-30).

## Fly.io (template)

1. Install [flyctl](https://fly.io/docs/hands-on/install-flyctl/) and log in.
2. Rename `app` in `fly.toml` (default placeholder `gametime-api`).
3. Create a volume in the same region as `primary_region`:

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

### First-time volume seed

After the first deploy, SSH in and populate config, data, and models on the volume:

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

Verify:

```bash
curl -s https://<your-app>.fly.dev/health | python3 -m json.tool
```

### Sizing

`fly.toml` starts at **shared-cpu-1x / 512mb**. LightGBM + 13-member ensemble load can OOM at 512mb; bump to **1gb** in `[vm] memory` if the machine restarts during predictor init.

### Daily data refresh

TASK-29 adds GitHub Actions cron to hit download on schedule. Until then, re-run `gametime-download` via `fly ssh console` or a one-off machine after games complete.

## Related

- [mlb_pregame_ops.md](mlb_pregame_ops.md) — download, train, local API
- `Dockerfile`, `docker-compose.yml`, `fly.toml` at repo root
