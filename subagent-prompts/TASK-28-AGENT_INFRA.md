# AGENT_INFRA — TASK-28: Container + local prod stack

## Your Role

You are **AGENT_INFRA**. You own Docker, compose, and Fly.io scaffolding for the predictions API.

You **do** add a production-ready API container, local `docker-compose` for integration testing, and `fly.toml` template (not a live deploy — human provides Fly/Vercel accounts).

You **do not** configure Vercel (TASK-30), write GitHub Actions cron (TASK-29), or change ensemble/model code.

## Project Context

- Branch: `task/TASK-28-docker-fly-scaffold` from **`main`**
- Commit format: `[AGENT_INFRA] TASK-28: short description`
- API entry: `uvicorn gametime.api.app:app --host 0.0.0.0 --port 8000`
- Deps: `pip install -e '.[api,mlb]'` (pybaseball needed if download runs in container)
- **Blocked by:** TASK-21 merged (API on `main`)

## Inputs Available

- Read `agents.md`, `STANDARDS.md`, `docs/mlb_pregame_ops.md`
- **Read STANDARDS.md before writing any code.**
- API env: `GAMETIME_ROOT`, `GAMETIME_CONFIG` (see `src/gametime/api/deps.py`)

## Architecture (locked)

```text
┌─────────────────────────────────────────┐
│  Fly.io Machine (TASK-30)               │
│  Volume: /data → GAMETIME_ROOT=/data      │
│    /data/data/mlb/processed/*.parquet   │
│    /data/models/mlb/pregame/            │
│  Process: uvicorn :8000                 │
└─────────────────────────────────────────┘
         ▲
         │ GAMETIME_API_URL (server-side only)
┌────────┴────────────────────────────────┐
│  Vercel — Next.js web/ (TASK-30)        │
│  BFF: /api/slate → Fly API              │
└─────────────────────────────────────────┘
```

## Your Task

### 1. `Dockerfile` (repo root or `deploy/Dockerfile.api`)

- Base: `python:3.11-slim`
- Install build deps if needed for lightgbm
- Copy `pyproject.toml`, `src/`, `configs/`
- `pip install -e '.[api,mlb]'`
- **Do not** `COPY data/` or `models/` into image — they live on a **persistent volume** at runtime
- `ENV GAMETIME_ROOT=/data` `GAMETIME_CONFIG=configs/mlb.yaml`
- `EXPOSE 8000`
- `CMD` uvicorn with `--host 0.0.0.0 --port 8000`
- Health: document `GET /health` for Fly checks

### 2. `.dockerignore`

Exclude `data/`, `models/`, `web/`, `.git`, `__pycache__`, `.venv`, `reports/`, large artifacts.

### 3. `docker-compose.yml` (repo root)

Services:

| Service | Purpose |
|---------|---------|
| `api` | Build from Dockerfile; mount `./data` → `/data/data` and `./models` → `/data/models` **or** single mount `./:/data` with adjusted paths — pick one, document clearly |
| `web` (optional) | Build `web/` Dockerfile **or** document “run web locally against api” for v1 |

Minimum: **`api` service only** with volume mounts so `docker compose up api` works when host has `data/` + `models/` from local `gametime-download` + train.

### 4. `fly.toml` (template)

- `app` placeholder `gametime-api` (comment: human renames)
- `primary_region` e.g. `sjc` or `iad`
- `[http_service]` internal_port 8000, force_https
- `[[mounts]]` source `gametime_data`, destination `/data`
- `[env]` `GAMETIME_ROOT=/data`, `GAMETIME_CONFIG=configs/mlb.yaml`
- `memory` / `cpu` — start `shared-cpu-1x`, `512mb` minimum (bump to `1gb` in docs if OOM during predictor load)
- `min_machines_running = 1` (avoid cold start on free tier where possible)

### 5. `docs/deploy.md` (seed section only — TASK-30 completes)

Document **first-time volume seed** on Fly:

```bash
fly volumes create gametime_data --size 10 --region <region>
fly deploy
fly ssh console -C "pip install -e '.[mlb]' && gametime-download --config configs/mlb.yaml"
```

Note: models must exist on volume (`ensemble.json`, LGBM txt) — copy from local train or document train-on-volume (slow; prefer `fly sftp` / `scp` from dev machine).

## Exact Deliverables

| Path | Action |
|------|--------|
| `Dockerfile` or `deploy/Dockerfile.api` | Create |
| `.dockerignore` | Create |
| `docker-compose.yml` | Create |
| `fly.toml` | Create (template) |
| `docs/deploy.md` | Create (partial — API/Docker/Fly seed) |
| `docs/mlb_pregame_ops.md` | Modify — link to `docs/deploy.md` |

## Off-Limits

- Vercel project wiring (TASK-30)
- `.github/workflows/` (TASK-29)
- Committing `data/` or `models/` to git
- Secrets in repo

## Git (worker)

- Commit on `task/TASK-28-docker-fly-scaffold`; do not push or open PR

## Definition of Done

- [ ] `docker compose build api` succeeds
- [ ] `docker compose up api` serves `/health` when host `data/` + `models/` mounted
- [ ] `fly.toml` validates (`fly config validate` if flyctl installed, or document manual check)
- [ ] `docs/deploy.md` explains volume layout under `/data`
- [ ] Committed on feature branch
- [ ] Handoff posted

## Handoff (required)

```text
Branch: task/TASK-28-docker-fly-scaffold
SHA: <commit>
Local smoke: docker compose up api + curl /health
Volume layout: <paths on /data>
Notes: recommended Fly memory, seed steps
```
