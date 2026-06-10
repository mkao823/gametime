# AGENT_FRONTEND — TASK-23: App shell + design system

## Your Role

You are **AGENT_FRONTEND**. You own the `web/` Next.js/React application: layout, routing, design tokens, shared components, and static content pages.

You **do** scaffold the Next.js app, implement global chrome per the design spec, render TASK-27 markdown, and add TypeScript API types aligned with TASK-21.

You **do not** fetch live slate data (TASK-24), build game detail (TASK-25), change Python/API code, or add deployment config (TASK-30).

## Project Context

- Project: gametime — MLB pregame ensemble + public slate site
- Branch: `task/TASK-23-app-shell` from **`main`** (TASK-21, TASK-26, TASK-27 already merged)
- Commit format: `[AGENT_FRONTEND] TASK-23: short description`
- **Parallel track D** — independent of model work (TASK-14+)

### Upstream artifacts (on `main`)

| Artifact | Path |
|----------|------|
| UX / visual spec | `docs/design/mlb-slate-mvp-spec.md` |
| Trust copy | `web/content/methodology.md`, `disclaimer.md`, `about.md`, `README.md` |
| API v1 schemas | `src/gametime/api/schemas.py` → OpenAPI at `/openapi.json` |
| Local API docs | `docs/mlb_pregame_ops.md` § Local API |

## Inputs Available

- Read `agents.md`, `STANDARDS.md` (Forward Standards for new `web/` files), `docs/design/mlb-slate-mvp-spec.md`
- Read `web/content/README.md` for frontmatter conventions
- Optional local API: `pip install -e '.[api]' && uvicorn gametime.api.app:app --reload` (not required for TASK-23 build)

## Orchestrator decisions (locked)

| Decision | Value |
|----------|-------|
| Canonical slate route | **`/`**; **`/mlb` → redirect `/`** |
| Win probability display | Integer % — `Math.round(win_prob_home * 100)` (TASK-24/25) |
| `include_members` | Game detail only, default `true` (TASK-25) |
| Date picker “today” | User local timezone (TASK-24) |
| Team display | Tricode only on cards (no logos) |
| Runs formatting | `Intl.NumberFormat` en-US, 1 decimal (TASK-24) |
| Theme | **Light-only** v1 |

## Your Task

Ship **app shell + design system** — everything TASK-24/25 will plug into.

### Stack

- **Next.js 14+** App Router, **TypeScript**
- Package root: **`web/`** (separate `package.json`; do not add React to root `pyproject.toml`)
- **CSS Modules** per component; global **`web/styles/tokens.css`** — copy token values from design spec § Design tokens
- **No inline styles** (`style={{...}}` forbidden)
- Markdown: `react-markdown` + `gray-matter` (or equivalent) for frontmatter

### Routes (TASK-23 scope)

| Route | Deliverable |
|-------|-------------|
| `/` | Slate **placeholder** — page title “MLB Slate”, short “Predictions load in TASK-24” note, correct `AppShell` layout |
| `/mlb` | `redirect('/')` |
| `/methodology` | `ProseLayout` + `web/content/methodology.md` |
| `/disclaimer` | `ProseLayout` + `disclaimer.md` + top **Callout** per design spec |
| `/about` | `ProseLayout` + `about.md` |
| `/mlb/game` | Optional stub (“Game detail — TASK-25”) inside shell |

### Components (TASK-23)

Implement from `docs/design/mlb-slate-mvp-spec.md` § Component inventory:

| Component | Notes |
|-----------|--------|
| `AppShell` | Header + `<main id="main-content">` + footer |
| `SiteHeader` | Wordmark “gametime”, nav: Slate, Methodology, Disclaimer; `aria-current="page"` |
| `SiteFooter` | Data sources one-liner + disclaimer link |
| `SkipLink` | “Skip to content” → `#main-content` |
| `ProseLayout` | YAML frontmatter → `<title>`/meta description; body markdown; **one `h1` from frontmatter `title`** — strip leading `# Title` from body if duplicate |
| `Callout` | Muted box for disclaimer intro |
| Shared `Link` styles | Token-based; `:focus-visible` ring per spec |

**Do not build** `GameCard`, `DatePicker`, `FreshnessBanner`, `MemberBreakdown` — those are TASK-24/25.

### TypeScript API types

Create `web/lib/api-types.ts` matching TASK-21 (hand-written is fine):

```typescript
export interface GamePrediction { /* fields from schemas.py */ }
export interface SlateResponse { date: string; season_start_year: number; games: GamePrediction[] }
export interface HealthResponse { status: string; games_max_date: string | null; model_dir: string; ensemble_members: string[] }
```

Add `web/lib/config.ts`:

```typescript
export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
```

Document in `web/README.md` — TASK-24 will use this.

### Prose / markdown

- Load markdown from `web/content/` at **build time** (`fs.readFile` in Server Components or `import` raw if configured)
- Support tables, links, headings in methodology copy
- Set `<metadata>` / `generateMetadata` from frontmatter `title` + `description`

### Accessibility (minimum)

Per design spec § Accessibility checklist:

- WCAG AA contrast via tokens
- `:focus-visible` on all interactives
- One `h1` per page
- `prefers-reduced-motion` respected (no animation required in TASK-23)

## Exact Deliverables

| Path | Action |
|------|--------|
| `web/package.json` | Create — `next`, `react`, `react-dom`, `typescript`, `react-markdown`, `gray-matter` |
| `web/tsconfig.json` | Create |
| `web/next.config.ts` (or `.js`) | Create |
| `web/README.md` | Create — `npm install`, `npm run dev`, `NEXT_PUBLIC_API_URL` |
| `web/styles/tokens.css` | Create — full token table from spec |
| `web/styles/globals.css` | Create — import tokens, base reset, prose styles |
| `web/components/AppShell.tsx` + `AppShell.module.css` | Create |
| `web/components/SiteHeader.tsx` + module | Create |
| `web/components/SiteFooter.tsx` + module | Create |
| `web/components/SkipLink.tsx` + module | Create |
| `web/components/ProseLayout.tsx` + module | Create |
| `web/components/Callout.tsx` + module | Create |
| `web/lib/markdown.ts` | Create — parse frontmatter + body |
| `web/lib/api-types.ts` | Create |
| `web/lib/config.ts` | Create |
| `web/app/layout.tsx` | Create — import globals, wrap `AppShell` |
| `web/app/page.tsx` | Create — slate placeholder |
| `web/app/methodology/page.tsx` | Create |
| `web/app/disclaimer/page.tsx` | Create |
| `web/app/about/page.tsx` | Create |
| `web/app/mlb/page.tsx` | Create — redirect `/` |
| `web/app/mlb/game/page.tsx` | Optional stub |
| `.gitignore` | Modify — `web/node_modules/`, `web/.next/`, `web/out/` |

## Off-Limits

- `src/gametime/**` Python code
- Live `/v1/slate` or `/health` fetching (TASK-24)
- Game detail UI (TASK-25)
- CORS / API changes (TASK-22)
- Docker / Vercel deploy (TASK-28/30)
- Team logos, odds UI, dark mode

## Git (worker)

- Commit on `task/TASK-23-app-shell` when verify passes
- **Do not** push, open PR, or merge — orchestrator handles after Handoff

## Definition of Done

- [ ] `cd web && npm install && npm run build` succeeds
- [ ] `npm run dev` — manually verify `/`, `/methodology`, `/disclaimer`, `/about`, `/mlb` redirect
- [ ] Tokens match `docs/design/mlb-slate-mvp-spec.md` (spot-check colors/spacing)
- [ ] No inline styles; CSS Modules + tokens only
- [ ] Frontmatter `title`/`description` used for metadata
- [ ] Code **committed** on feature branch (not pushed)
- [ ] Handoff block posted

## Handoff (required)

```text
Branch: task/TASK-23-app-shell
SHA: <commit>
Run: cd web && npm run dev  # default http://localhost:3000
Routes verified: /, /methodology, /disclaimer, /about, /mlb → /
Stack: Next.js <version>, markdown lib <name>
Notes: any deviations from spec; ready for TASK-24 slate fetch
```

## Unblocks

- **TASK-24** — Daily slate page (`GameCard`, `DatePicker`, `/v1/slate` + `/health`)
- **TASK-25** — Game detail (after TASK-24)
