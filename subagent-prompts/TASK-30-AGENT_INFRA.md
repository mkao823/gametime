# AGENT_INFRA — TASK-30: Production deploy (Vercel + Fly.io)

## Your Role

You are **AGENT_INFRA**. You wire **production hosting** for the public slate site:

- **Vercel** → `web/` (Next.js)
- **Fly.io** → Python predictions API (from TASK-28)

You **do** complete `docs/deploy.md`, add Vercel config, optional deploy smoke workflow, and env var contract.

You **do not** change model/member code, enable paid tiers without documenting cost, or store secrets in git.

## Project Context

- Branch: `task/TASK-30-vercel-fly-deploy` from **`main`**
- Commit format: `[AGENT_INFRA] TASK-30: short description`
- **Blocked by:** TASK-28 (Docker/Fly), TASK-23+ (web app), TASK-21 (API)
- **Soft block:** TASK-29 (cron) can merge in parallel; deploy works without cron but data goes stale

## Hosting choice (orchestrator-locked)

| Layer | Provider | Tier |
|-------|----------|------|
| Frontend | **[Vercel](https://vercel.com)** Hobby (free) | Next.js from `web/` |
| API | **[Fly.io](https://fly.io)** | 1 shared-cpu VM + volume; free allowance / low cost |
| Cron | **GitHub Actions** (TASK-29) | `fly ssh` download on volume |

**Not recommended:** Vercel serverless for Python ML API; Render free (sleep/cold start).

## Inputs Available

- Read `agents.md`, `STANDARDS.md`, `docs/mlb_pregame_ops.md`, `docs/deploy.md` (from TASK-28)
- **Read STANDARDS.md before writing any code.**
- `web/README.md` — `GAMETIME_API_URL` BFF proxy pattern

## Your Task

### 1. Vercel configuration

| Item | Spec |
|------|------|
| Root directory | `web` (monorepo setting in Vercel dashboard **or** `vercel.json` at repo root pointing to web — prefer `web/vercel.json`) |
| Build | `npm run build` |
| Output | Next.js default |
| Env (Production) | `GAMETIME_API_URL=https://<fly-app>.fly.dev` |
| Env | Do **not** set `NEXT_PUBLIC_API_URL` to Fly for browser direct calls — BFF only |

Add `web/vercel.json` if needed (framework defaults usually sufficient).

### 2. Fly.io production checklist (document + validate `fly.toml`)

Human steps in `docs/deploy.md` (you write the runbook):

1. `fly apps create gametime-api` (or name in `fly.toml`)
2. `fly volumes create gametime_data --size 10 --region <region>`
3. `fly deploy`
4. Seed volume (download + copy models) — link TASK-28 seed section
5. `curl https://<app>.fly.dev/health`
6. Optional: TASK-22 CORS — **not required** if Vercel BFF proxies server-side only

### 3. End-to-end wiring

```text
User → https://<vercel-domain>/
     → Next.js /api/slate (server)
     → https://<fly-app>.fly.dev/v1/slate
```

Verify CORS is irrelevant for browser (only server-side fetch from Vercel to Fly). Use **HTTPS** Fly URL.

### 4. Optional smoke workflow

`.github/workflows/deploy-smoke.yml`:

- `workflow_dispatch` only (or after deploy hook later)
- Curl Fly `/health` and Vercel homepage (URL from secret `VERCEL_PRODUCTION_URL`)
- Non-blocking if secrets not set — document as optional

### 5. Complete `docs/deploy.md`

Sections:

1. **Architecture** (diagram above)
2. **Prerequisites** — Fly account, Vercel account, GitHub repo, local `data/` + `models/` for seed
3. **Fly API deploy** — step-by-step
4. **Vercel frontend deploy** — import repo, set root `web`, env vars
5. **Secrets table**

| Secret | Where | Purpose |
|--------|-------|---------|
| `FLY_API_TOKEN` | GitHub | TASK-29 cron |
| `GAMETIME_API_URL` | Vercel | BFF → Fly |

6. **Alternates** — Render free (cold start), Oracle VM (advanced)
7. **Cost notes** — Fly volume + VM may exceed free tier at scale; Hobby Vercel sufficient for MVP
8. **Troubleshooting** — OOM → bump Fly memory; stale slate → check cron + `/health` `games_max_date`

### 6. `README.md`

Add short **Deploy** section linking to `docs/deploy.md`.

## Exact Deliverables

| Path | Action |
|------|--------|
| `docs/deploy.md` | Complete (merge TASK-28/29 content if needed) |
| `web/vercel.json` | Create if required |
| `.github/workflows/deploy-smoke.yml` | Create (optional smoke) |
| `README.md` | Modify — deploy link |
| `web/README.md` | Modify — production env vars |

## Off-Limits

- Changing API routes or ensemble
- TASK-31 E2E Playwright (separate QA task)
- Committing API keys

## Git (worker)

- Commit on `task/TASK-30-vercel-fly-deploy`; do not push or open PR

## Definition of Done

- [ ] `docs/deploy.md` is a complete human runbook (Fly + Vercel + env vars)
- [ ] Vercel config documented (root `web`, `GAMETIME_API_URL`)
- [ ] Fly `fly.toml` from TASK-28 referenced and consistent
- [ ] No secrets in repo
- [ ] Committed on feature branch
- [ ] Handoff posted (URLs placeholders OK)

## Handoff (required)

```text
Branch: task/TASK-30-vercel-fly-deploy
SHA: <commit>
Docs: docs/deploy.md
Vercel: root directory web; env GAMETIME_API_URL
Fly: app name, volume name, region
Smoke: optional workflow name + how to run
Human steps remaining: create Fly app, Vercel project, add secrets, first seed
```

## Unblocks

- **TASK-31** AGENT_QA — E2E smoke against staging/production URLs
