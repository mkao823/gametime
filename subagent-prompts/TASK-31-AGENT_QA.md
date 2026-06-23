# AGENT_QA — TASK-31: E2E smoke (Playwright)

## Your Role

You are **AGENT_QA**. You add **Playwright end-to-end smoke tests** for the MLB slate web app and wire a **local CI path** (docker API + Next.js) plus optional **production smoke** via GitHub Actions secrets.

You **do** scaffold Playwright, write smoke specs, extend `deploy-smoke.yml` or add `e2e.yml`, and document how to run tests locally.

You **do not** change ensemble/model code, API business logic, or deploy secrets. Do not commit tunnel tokens or Vercel credentials.

## Project Context

- Branch: `task/TASK-31-e2e-smoke` from **`main`** (`f8179b9` — includes TASK-34 fast slate)
- Commit format: `[AGENT_QA] TASK-31: short description`
- **Blocked by:** TASK-32 ✅, TASK-33 ✅, TASK-34 ✅ (slate loads in <10s for today)
- Stack: Vercel `web/` BFF (`/api/slate`, `/api/game`, `/api/health`) → Python API `/v1/*`

## Inputs Available

- Read `agents.md`, `docs/deploy-local-tunnel.md`, `docs/deploy.md`
- Existing optional workflow: `.github/workflows/deploy-smoke.yml` (curl-based; extend, do not delete Fly/Vercel steps)
- Web routes: `/` (slate), `/mlb/game` (detail), `/methodology`, `/about`, `/disclaimer`
- Sample slate date with parquet coverage: **`2024-06-15`** (fast, stable for CI)

## Your Task

### 1. Playwright scaffold

Add Playwright under `web/` (preferred — keeps Next deps together):

| Path | Action |
|------|--------|
| `web/package.json` | Add `@playwright/test` devDep; scripts `test:e2e`, `test:e2e:ui` |
| `web/playwright.config.ts` | Base URL from `PLAYWRIGHT_BASE_URL` (default `http://127.0.0.1:3000`); reasonable timeouts (slate BFF may take ~10s on cold API) |
| `web/e2e/` | Smoke specs |

Run `npx playwright install chromium` once locally; document in Handoff (CI uses `npx playwright install --with-deps chromium`).

### 2. Smoke specs (minimum)

**`web/e2e/slate.spec.ts`**

- Visit `/?date=2024-06-15`
- Assert page title or heading contains "MLB Slate"
- Assert at least one game card visible (use stable selectors: `data-testid` if you add them, or role/text patterns)
- Assert cards show start time text (TASK-33) when API returns `start_time`

**`web/e2e/game-detail.spec.ts`**

- From slate page, click first game card link
- Assert game detail route loads (`/mlb/game`)
- Assert ensemble total/margin or member section visible

**`web/e2e/static-pages.spec.ts`**

- `/methodology`, `/about`, `/disclaimer` return 200 and expected heading

**`web/e2e/api-health.spec.ts`** (optional but recommended)

- `GET /api/health` returns JSON with `status: ok` when API is reachable

Use `date=2024-06-15` in CI — avoids depending on today's schedule.

### 3. Local run orchestration

Document and optionally script:

```bash
# Terminal 1
docker compose up api

# Terminal 2
cd web && GAMETIME_API_URL=http://127.0.0.1:8000 npm run dev

# Terminal 3
cd web && GAMETIME_API_URL=http://127.0.0.1:8000 npx playwright test
```

`web` server reads `GAMETIME_API_URL` via `@/lib/server-api` — must point at running API for BFF proxies.

### 4. CI workflow

Extend **`.github/workflows/deploy-smoke.yml`** or add **`web-e2e.yml`**:

| Trigger | `workflow_dispatch` + optional `pull_request` paths `web/**` |
| Job | checkout → setup Node → `npm ci` in `web/` → start API via `docker compose up -d api` → wait for `/health` → `npm run build && npm run start` (or `next dev`) → `npx playwright test` |

Keep Fly/Vercel curl steps in `deploy-smoke.yml` **optional** (skip when secrets unset). E2E job should **not** require Vercel or tunnel secrets.

Add `PLAYWRIGHT_BASE_URL=http://127.0.0.1:3000` in CI.

### 5. Docs

Add short **E2E** section to `docs/deploy-local-tunnel.md` or `web/README.md`:

- Prereqs: docker API + seeded `data/` + `models/`
- Commands to run Playwright locally
- Optional production smoke: set `VERCEL_PRODUCTION_URL` + ensure `GAMETIME_API_URL` on Vercel points at live tunnel

## Exact Deliverables

| Path | Action |
|------|--------|
| `web/package.json` | Playwright scripts + devDep |
| `web/playwright.config.ts` | Create |
| `web/e2e/*.spec.ts` | Create (≥3 spec files above) |
| `web/components/*` | Optional minimal `data-testid` on `GameCard` / slate grid only if needed for stable selectors |
| `.github/workflows/deploy-smoke.yml` or `web-e2e.yml` | CI job |
| `docs/deploy-local-tunnel.md` or `web/README.md` | E2E run instructions |

## Off-Limits

- Ensemble members, `train.py`, ingest (TASK-14+)
- Changing API response schema beyond optional test IDs
- Committing secrets, tunnel URLs, or `.env` files
- Replacing unit tests in `tests/test_*.py`

## Git (worker)

- Commit on `task/TASK-31-e2e-smoke`; do not push or open PR

## Definition of Done

- [ ] `cd web && npx playwright test` passes against local `docker compose api` + `npm run dev` with `GAMETIME_API_URL=http://127.0.0.1:8000`
- [ ] Slate smoke uses `date=2024-06-15` and asserts ≥1 game card
- [ ] Game detail navigation smoke passes
- [ ] Static pages smoke passes
- [ ] CI workflow defined (passes or documented skip if docker unavailable on runner — prefer `ubuntu-latest` + docker compose)
- [ ] `cd web && npm run build` still passes
- [ ] `PYTHONPATH=src python3 -m pytest tests/test_api_predictions.py -q` still passes (no API regressions)
- [ ] Handoff posted

## Handoff (required)

```text
Branch: task/TASK-31-e2e-smoke
SHA: <commit>
Local run: <3-terminal commands>
CI: workflow name + how to trigger
Specs: list e2e files + what each asserts
Sample date: 2024-06-15
Production smoke (optional): VERCEL_PRODUCTION_URL + tunnel prerequisite
Notes: any flake / timeout tuning
```

## Unblocks

- Confidence for Vercel + tunnel deploys after TASK-32
- Regression gate before TASK-14 model work touches shared code
