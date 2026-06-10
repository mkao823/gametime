# AGENT_FRONTEND — TASK-24: Daily slate page

## Your Role

You are **AGENT_FRONTEND**. You implement the live MLB daily slate on `/` using the Predictions API, per the design spec.

You **do** build slate UI components, date navigation, freshness banner, loading/error/empty states, and a same-origin API proxy so the browser avoids CORS issues (TASK-22 optional).

You **do not** build game detail / member breakdown (TASK-25), change Python API code, or deploy (TASK-30).

## Project Context

- Branch: `task/TASK-24-daily-slate` from **`main`** (merge/rebase after TASK-23 PR #14 if not yet on `main`)
- Commit format: `[AGENT_FRONTEND] TASK-24: short description`
- Builds on: TASK-23 `web/` shell (`AppShell`, tokens, `api-types.ts`, `config.ts`)
- Design: `docs/design/mlb-slate-mvp-spec.md` § Daily slate, Data freshness UX, Component inventory
- Backend: TASK-21 `GET /health`, `GET /v1/slate?date=&regular_season=true`

## Inputs Available

- Read `agents.md`, `STANDARDS.md` (Forward Standards for new `web/` files)
- Read `docs/design/mlb-slate-mvp-spec.md`, `web/README.md`
- API types: `web/lib/api-types.ts`
- Local dev: terminal 1 `uvicorn gametime.api.app:app --reload`; terminal 2 `cd web && npm run dev`

## Orchestrator decisions (locked)

| Decision | Value |
|----------|-------|
| Win % display | Integer — `Math.round(win_prob_home * 100)`; away winner → `100 - round` |
| Runs display | `Intl.NumberFormat` en-US, 1 decimal |
| Date default | User **local timezone** today |
| URL sync | `/?date=YYYY-MM-DD` shareable |
| `include_members` | **false** on slate (`/v1/slate`) |
| Card link | `/mlb/game?home=&away=&date=` (TASK-25 stub OK) |
| CORS workaround | **Next.js Route Handlers** proxy `/api/health` + `/api/slate` → Python API (server-side fetch) |

## Your Task

Replace the TASK-23 placeholder on `/` with a fully functional **daily slate page**.

### API access pattern (required)

Browser must **not** call `http://127.0.0.1:8000` directly (CORS not enabled until TASK-22).

Implement BFF proxies:

| Next route | Upstream |
|------------|----------|
| `GET web/app/api/health/route.ts` | `{API_BASE}/health` |
| `GET web/app/api/slate/route.ts` | `{API_BASE}/v1/slate?date=&regular_season=` |

`API_BASE` for server fetch:

```typescript
// web/lib/server-api.ts
export const SERVER_API_BASE =
  process.env.GAMETIME_API_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://127.0.0.1:8000";
```

Client hooks fetch **`/api/health`** and **`/api/slate?date=`** only.

Document in `web/README.md`: run Python API + set `GAMETIME_API_URL` in production.

### Components to create

| Component | Spec reference |
|-----------|----------------|
| `FreshnessBanner` | `games_max_date` vs selected date; `role="status"`; warning tokens |
| `DatePicker` | Prev/next, native date input, Today shortcut; min 44×44px targets |
| `GameCard` | Tricode matchup, total, pick, margin; winner styling; full-card link |
| `GameCardSkeleton` | Shimmer; respect `prefers-reduced-motion` |
| `EmptySlate` | Zero games, friendly copy |
| `ErrorBanner` | `role="alert"` + Retry button |
| `SlatePage` (or compose in `page.tsx`) | Orchestrates health + slate fetch |

Implement `useDataFreshness(health, selectedDate)` hook per design spec (can live in `web/lib/useDataFreshness.ts`).

### Page behavior (`web/app/page.tsx`)

Convert to **client slate** or use a client child `SlateView` with:

1. Read `date` from `useSearchParams()`; default local today as `YYYY-MM-DD`
2. On date change → update URL `?date=` via `router.replace` (shareable links)
3. Parallel fetch `/api/health` + `/api/slate?date=`
4. States: loading (skeletons), empty (`games.length === 0`), error (banner + retry), success (grid)
5. Meta line: `{n} games · Regular season`
6. `h1`: “MLB Slate”
7. 2-column grid at `≥768px` per spec

### Formatting helpers

Create `web/lib/format.ts`:

```typescript
formatRuns(n: number)      // "9.2 runs"
formatWinPct(home, winner, win_prob_home)  // integer %
formatMargin(home, away, pred_margin)      // "NYY −1.1"
```

### Accessibility

- Game card `aria-label`: e.g. “Boston at New York, predicted total 9.2, pick New York”
- Date controls: `aria-label` on prev/next
- One `h1` per page

## Exact Deliverables

| Path | Action |
|------|--------|
| `web/app/api/health/route.ts` | **Create** — proxy |
| `web/app/api/slate/route.ts` | **Create** — proxy; forward query params |
| `web/lib/server-api.ts` | **Create** — server-side API base URL |
| `web/lib/format.ts` | **Create** — display formatters |
| `web/lib/useDataFreshness.ts` | **Create** — stale banner logic |
| `web/components/FreshnessBanner.tsx` + module | **Create** |
| `web/components/DatePicker.tsx` + module | **Create** |
| `web/components/GameCard.tsx` + module | **Create** |
| `web/components/GameCardSkeleton.tsx` + module | **Create** |
| `web/components/EmptySlate.tsx` + module | **Create** |
| `web/components/ErrorBanner.tsx` + module | **Create** |
| `web/components/SlateView.tsx` + module | **Create** — main client composition |
| `web/app/page.tsx` | **Modify** — wire `SlateView` + `Suspense` if needed for `useSearchParams` |
| `web/README.md` | **Modify** — dev workflow: API + web, proxy note |

## Off-Limits

- `src/gametime/api/**` (TASK-22 for CORS on Python API is optional if BFF works)
- Game detail page logic beyond link target (TASK-25)
- `include_members=true` on slate fetch
- Inline styles

## Git (worker)

- Commit on `task/TASK-24-daily-slate`; do not push or open PR

## Definition of Done

- [ ] `cd web && npm run build` succeeds
- [ ] With API running: slate shows games for a known historical date (e.g. `?date=2024-06-15`)
- [ ] Date picker updates URL and refetches
- [ ] Freshness banner shows when `games_max_date < selectedDate`
- [ ] Empty + error + loading states implemented
- [ ] No inline styles; CSS Modules + tokens
- [ ] Committed on feature branch
- [ ] Handoff posted

## Handoff (required)

```text
Branch: task/TASK-24-daily-slate
SHA: <commit>
Run: uvicorn gametime.api.app:app & cd web && npm run dev
Verified: /?date=2024-06-15 shows N games; /api/slate proxy works
Notes: any edge cases (API down, empty slate)
```

## Unblocks

- **TASK-25** — Game detail page (`/mlb/game`, `include_members=true`)
