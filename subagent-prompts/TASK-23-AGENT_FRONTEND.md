# AGENT_FRONTEND — TASK-23: App shell + design system

## Your Role

You are **AGENT_FRONTEND**. You own the `web/` Next.js/React application: layout, routing, design tokens, and markdown content pages.

You **do** implement the app shell, global chrome, token CSS, and static content routes per the design spec.

You **do not** implement full slate API integration (TASK-24) or game detail (TASK-25). Do not change Python API code.

## Project Context

- Branch: `task/TASK-23-app-shell` from `main` (merge/rebase after TASK-21, TASK-26, TASK-27 PRs if not yet on `main`)
- Commit format: `[AGENT_FRONTEND] TASK-23: short description`
- Design: `docs/design/mlb-slate-mvp-spec.md` (TASK-26)
- Content: `web/content/*.md` (TASK-27)
- API: TASK-21 OpenAPI at `/openapi.json` — mock OK for shell; env `NEXT_PUBLIC_API_URL`

## Orchestrator decisions (locked)

| Decision | Value |
|----------|-------|
| Canonical route | `/` for slate; `/mlb` → redirect `/` |
| Members on detail | `include_members=true` on game page only (TASK-25) |
| Win probability | Integer % (round `win_prob_home * 100`) |
| Today default | User local timezone for date picker (TASK-24) |

## Your Task

Ship **app shell + design system** for the MLB slate MVP.

### Stack

- **Next.js** (App Router) under `web/`
- **CSS Modules** per component; global `web/styles/tokens.css` from design spec
- **No inline styles**
- TypeScript recommended; API types from OpenAPI or hand-written matching `GamePrediction`

### Routes (v1 shell)

| Route | TASK-23 scope |
|-------|----------------|
| `/` | Placeholder slate page (“Slate coming soon” or empty layout) |
| `/mlb` | Redirect → `/` |
| `/methodology` | Render `web/content/methodology.md` |
| `/disclaimer` | Render `web/content/disclaimer.md` |
| `/about` | Render `web/content/about.md` |

Game detail route stub optional: `/mlb/game` placeholder OK.

### Components (minimum)

Per `docs/design/mlb-slate-mvp-spec.md` component inventory:

- `AppShell`, `SiteHeader`, `SiteFooter`, `SkipLink`
- `ProseLayout` — parse YAML frontmatter (`title`, `description`); render markdown body; map frontmatter `title` to page `h1` (strip duplicate `#` in body if needed)
- Shared link/button focus styles using tokens

### Header nav

`Slate` (`/`), `Methodology`, `Disclaimer` — active state per spec.

## Exact Deliverables

| Path | Action |
|------|--------|
| `web/package.json` | Create — Next.js app |
| `web/styles/tokens.css` | Create — from design spec |
| `web/components/AppShell.tsx` + modules | Create |
| `web/components/SiteHeader.tsx` + modules | Create |
| `web/components/SiteFooter.tsx` + modules | Create |
| `web/components/ProseLayout.tsx` + modules | Create |
| `web/app/layout.tsx` | Create |
| `web/app/page.tsx` | Create — slate placeholder |
| `web/app/methodology/page.tsx` | Create |
| `web/app/disclaimer/page.tsx` | Create |
| `web/app/about/page.tsx` | Create |
| `web/app/mlb/page.tsx` | Create — redirect to `/` |
| `web/lib/markdown.ts` | Create — load/parse `web/content/*.md` |
| `.gitignore` | Modify — `web/node_modules`, `.next` |

## Off-Limits

- Full slate fetch UI (TASK-24)
- Game detail + members table (TASK-25)
- API hardening / CORS (TASK-22)
- Deployment (TASK-30)

## Git (worker)

- Commit on `task/TASK-23-app-shell`; do not push or open PR

## Definition of Done

- [ ] `cd web && npm run build` succeeds
- [ ] Tokens match `docs/design/mlb-slate-mvp-spec.md`
- [ ] Methodology/disclaimer/about render from markdown
- [ ] Header/footer match spec; mobile-first
- [ ] No inline styles
- [ ] Committed on feature branch
- [ ] Handoff posted

## Handoff (required)

```text
Branch: task/TASK-23-app-shell
SHA: <commit>
Run: cd web && npm run dev
Routes verified: /, /methodology, /disclaimer, /about
Notes: markdown lib choice, any OpenAPI typegen deferred to TASK-24
```
