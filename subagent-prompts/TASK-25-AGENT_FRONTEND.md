# AGENT_FRONTEND — TASK-25: Game detail + member breakdown

## Your Role

You are **AGENT_FRONTEND**. You implement the **game detail page** at `/mlb/game` with predicted scoreline and collapsible ensemble member breakdown.

You **do** add a BFF proxy for `/v1/game`, detail UI components, and wire the TASK-24 stub into a live page.

You **do not** change Python API code, slate page logic (TASK-24), or deployment (TASK-30).

## Project Context

- Branch: `task/TASK-25-game-detail` from **`main`** (rebase after TASK-24 PR #15 merges if needed)
- Commit format: `[AGENT_FRONTEND] TASK-25: short description`
- Design: `docs/design/mlb-slate-mvp-spec.md` § Game detail (TASK-25)
- API: `GET /v1/game?home=&away=&date=&include_members=true` (404 when not on slate)

## Inputs Available

- Read `agents.md`, `STANDARDS.md`, `docs/design/mlb-slate-mvp-spec.md`, `web/README.md`
- Reuse: `web/lib/format.ts`, `web/lib/api-types.ts`, `web/lib/server-api.ts`, `ErrorBanner`, token CSS
- TASK-24 patterns: `SlateView`, `GameCard` link targets `/mlb/game?home=&away=&date=`

## Orchestrator decisions (locked)

| Decision | Value |
|----------|-------|
| API fetch | `include_members=true` **always** on game detail |
| Win % | Integer via existing `formatWinPct` |
| Member table order | `/api/health` → `ensemble_members` if available; else alphabetical |
| Member accordion | **Collapsed by default** (all breakpoints) |
| Back link | `/?date={date}` preserves slate date |
| BFF | Client fetches **`/api/game`** only (not Python host directly) |

## Your Task

Replace `web/app/mlb/game/page.tsx` stub with a full **game detail** experience.

### BFF proxy

Create `web/app/api/game/route.ts`:

| Query param | Forward to |
|-------------|------------|
| `home`, `away`, `date` | Required (422 from API if missing/invalid) |
| `regular_season` | Default `true` |
| `include_members` | Always `true` upstream |

Mirror error handling from `web/app/api/slate/route.ts` (502 on connection failure; forward API status for 404/422).

### Components

| Component | Spec |
|-----------|------|
| `BackLink` | “← Back to slate” → `/?date=` |
| `ScorelineCard` | “Predicted final” label; away @ home scores; total; winner line; winner side uses `--color-winner` |
| `MemberBreakdown` | Collapsible `<button aria-expanded>` + table (`member_totals`, `member_margins`); signed margin with `+` for home-favored; hide entire section if no member keys |
| `GameDetailView` | Client component: read `home`, `away`, `date` from `useSearchParams()`; fetch `/api/game` + optional `/api/health` for member order; loading / error / 404 / success |
| `ScorelineSkeleton` | Loading state per spec |

### Page wiring

`web/app/mlb/game/page.tsx`:

- Wrap `GameDetailView` in `<Suspense>` (required for `useSearchParams`)
- `generateMetadata` optional: `{away} @ {home}` from search params when possible

### URL contract

Required query params: `home`, `away`, `date` (ISO `YYYY-MM-DD`).

| Missing param | UX |
|---------------|-----|
| Any required param missing | Friendly message + link to `/` (not a crash) |
| API 404 | “Game not found on this date” + back link |
| API error | Reuse `ErrorBanner` + retry |

### Formatting

Reuse `web/lib/format.ts` — do not duplicate. Add helpers only if needed, e.g.:

```typescript
formatScoreline(away, home, predAway, predHome, winner)
formatMemberMargin(m: number) // "+1.2" / "-0.5"
formatDisplayDate(date) // if not already in format.ts from TASK-24
```

### Accessibility

- `h1`: `{away} @ {home}`
- `h2`: “Predicted outcome”, “Member breakdown”
- Scoreline not presented as live score — keep “Predicted final” sublabel
- Collapsible: `aria-controls` + panel `id`

## Exact Deliverables

| Path | Action |
|------|--------|
| `web/app/api/game/route.ts` | **Create** |
| `web/components/BackLink.tsx` + module | **Create** |
| `web/components/ScorelineCard.tsx` + module | **Create** |
| `web/components/ScorelineSkeleton.tsx` + module | **Create** |
| `web/components/MemberBreakdown.tsx` + module | **Create** |
| `web/components/GameDetailView.tsx` + module | **Create** |
| `web/app/mlb/game/page.tsx` | **Modify** — replace stub |
| `web/app/mlb/game/page.module.css` | **Modify** or remove if unused |
| `web/lib/format.ts` | **Modify** only if new helpers needed |
| `web/README.md` | **Modify** — game route + `/api/game` |

## Off-Limits

- `src/gametime/**`
- Slate page changes beyond verifying `GameCard` links (should already point here)
- Quantile bands (TASK-15)

## Git (worker)

- Commit on `task/TASK-25-game-detail`; do not push or open PR

## Definition of Done

- [ ] `cd web && npm run build` succeeds
- [ ] With API running: `/mlb/game?home=NYY&away=BOS&date=2024-06-15` shows scoreline + member table
- [ ] Invalid/missing params handled gracefully
- [ ] 404 state when game off-slate
- [ ] No inline styles
- [ ] Committed on feature branch
- [ ] Handoff posted

## Handoff (required)

```text
Branch: task/TASK-25-game-detail
SHA: <commit>
Run: uvicorn + npm run dev
Verified URL: /mlb/game?home=...&away=...&date=2024-06-15
Member breakdown: collapsed default, expands on click
Notes: edge cases
```

## Unblocks

- **TASK-30** — full MVP path for Vercel deploy (slate + detail)
- **TASK-31** — E2E can assert game detail from slate card click
