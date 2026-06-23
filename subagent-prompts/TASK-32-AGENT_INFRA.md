# AGENT_INFRA — TASK-32: Local API + Cloudflare Tunnel (free MVP)

## Your Role

You are **AGENT_INFRA**. You document and scaffold **free hosting** for the predictions API:

- **Local machine** — `docker compose up api` (existing TASK-28 layout)
- **Cloudflare Tunnel** — expose `localhost:8000` as HTTPS without opening router ports
- **Vercel** — unchanged; `GAMETIME_API_URL` points at the tunnel hostname

You **do** add runbook docs, example `cloudflared` config, and optional launchd/systemd snippets for tunnel + daily download.

You **do not** remove Fly.io docs (mark as alternate/paid), change ensemble code, or commit secrets/tunnel tokens.

## Project Context

- Branch: `task/TASK-32-local-cloudflare-tunnel` from **`main`**
- Commit format: `[AGENT_INFRA] TASK-32: short description`
- **Supersedes for MVP:** Fly.io production path (human chose free local hosting)
- **TASK-29** (Fly GHA cron) — **do not extend**; document local cron instead

## Hosting choice (orchestrator-locked)

| Layer | Provider | Notes |
|-------|----------|-------|
| Frontend | **Vercel** Hobby | `web/` — unchanged |
| API | **Local Docker** | `docker-compose.yml` — bind-mount `./data`, `./models` |
| Public HTTPS | **Cloudflare Tunnel** | `cloudflared` → `http://127.0.0.1:8000` |
| Data refresh | **Local cron** or manual | `gametime-download` on host (not Fly ssh) |

```text
User → https://<vercel-domain>/
     → Next.js /api/slate (server)
     → https://<tunnel-hostname>/v1/slate
          ↑ cloudflared on local machine
          ↑ docker compose api :8000
```

## Inputs Available

- Read `agents.md`, `STANDARDS.md`, `docs/mlb_pregame_ops.md`, `docs/deploy.md`
- **Read STANDARDS.md before writing any code.**
- Existing: `Dockerfile`, `docker-compose.yml`, `web/README.md`, `web/vercel.json`

## Your Task

### 1. Primary runbook — `docs/deploy-local-tunnel.md`

Step-by-step for a human operator:

| Section | Content |
|---------|---------|
| Prerequisites | Docker, local `data/` + `models/` seeded (`gametime-download`, `gametime-pregame-train`) |
| Start API | `docker compose up -d api` + `curl localhost:8000/health` |
| Cloudflare account | Free tier; install `cloudflared` |
| Quick tunnel (dev) | `cloudflared tunnel --url http://127.0.0.1:8000` → copy `*.trycloudflare.com` URL |
| Named tunnel (stable URL) | Create tunnel in CF dashboard; route DNS `api.<yourdomain>`; config points to `http://127.0.0.1:8000` |
| Vercel wiring | Set `GAMETIME_API_URL=https://api.<yourdomain>` (or trycloudflare URL for dev) |
| Verify E2E | Vercel slate loads; `/health` via tunnel returns `games_max_date` |
| Daily download | `crontab` example: `0 14 * * * cd /path/to/gametime && gametime-download --config configs/mlb.yaml` (host paths, not inside container) |
| Keep-alive | Machine must stay on; note sleep/laptop lid risks |
| Limitations | Not multi-region; home uptime; tunnel token is secret |

### 2. Example cloudflared config

Add **`config/cloudflared.yml.example`** (no real credentials):

```yaml
# Copy to ~/.cloudflared/config.yml after: cloudflared tunnel create gametime-api
tunnel: <TUNNEL_UUID>
credentials-file: /path/to/<TUNNEL_UUID>.json

ingress:
  - hostname: api.example.com
    service: http://127.0.0.1:8000
  - service: http_status:404
```

Document how to obtain `TUNNEL_UUID` and credentials JSON from Cloudflare Zero Trust dashboard.

### 3. Optional process helpers (examples only, not required to run)

| File | Purpose |
|------|---------|
| `scripts/local-api-up.sh` | `docker compose up -d api` + health wait |
| `scripts/cloudflared-run.sh.example` | `cloudflared tunnel --config config/cloudflared.yml run` |

Keep scripts minimal; no new Python dependencies.

### 4. Update existing docs (do not delete Fly content)

| File | Change |
|------|--------|
| `docs/deploy.md` | Add **§ Free MVP (recommended)** at top linking to `deploy-local-tunnel.md`; move Fly/Vercel-Fly sections under **§ Alternate: Fly.io (paid)** |
| `README.md` | Deploy link → local tunnel doc as default |
| `web/README.md` | `GAMETIME_API_URL` examples: tunnel URL + local dev |
| `docs/mlb_pregame_ops.md` | One line: production API may run locally + tunnel (link) |

### 5. TASK-29 / Fly cron

In `docs/deploy.md` alternate section, note TASK-29 Fly workflow is **optional** and **not used** for local-tunnel MVP. Do **not** delete `.github/workflows/mlb-data-refresh.yml` (may exist on open PR #19) — add a comment in deploy doc that local MVP uses host cron instead.

## Exact Deliverables

| Path | Action |
|------|--------|
| `docs/deploy-local-tunnel.md` | Create — primary free runbook |
| `config/cloudflared.yml.example` | Create |
| `docs/deploy.md` | Modify — local-first structure |
| `README.md` | Modify — deploy pointer |
| `web/README.md` | Modify — env examples |
| `scripts/local-api-up.sh` | Create (optional, if useful) |
| `scripts/cloudflared-run.sh.example` | Create (optional) |

## Off-Limits

- Removing `fly.toml` / Docker scaffold (still valid for local compose)
- Python API route changes
- Committing `.cloudflared/*.json` credentials
- TASK-31 Playwright (separate QA task)
- TASK-14 model work

## Git (worker)

- Commit on `task/TASK-32-local-cloudflare-tunnel`; do not push or open PR

## Definition of Done

- [ ] `docs/deploy-local-tunnel.md` is complete enough for human to go from zero → tunnel URL → Vercel `GAMETIME_API_URL`
- [ ] `docker compose up api` + local health documented (reuse TASK-28)
- [ ] Named tunnel + quick tunnel both documented
- [ ] Local daily download cron documented
- [ ] `docs/deploy.md` reflects local-first; Fly demoted to alternate
- [ ] No secrets in repo
- [ ] Committed on feature branch
- [ ] Handoff posted

## Handoff (required)

```text
Branch: task/TASK-32-local-cloudflare-tunnel
SHA: <commit>
Quick tunnel command: cloudflared tunnel --url http://127.0.0.1:8000
Named tunnel hostname placeholder: api.<domain>
Vercel env: GAMETIME_API_URL=https://...
Local cron example: <crontab line>
Notes: machine must stay on; TASK-29 Fly cron N/A for this path
```

## Unblocks

- **TASK-31** — E2E can target Vercel + tunnel `/health` URL (after human creates tunnel)
