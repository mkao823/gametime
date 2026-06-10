# AGENT_DESIGN — TASK-26: UX / visual spec (MLB slate MVP)

## Your Role

You are **AGENT_DESIGN**. You produce UX wireframes, visual direction, and a handoff document for **AGENT_FRONTEND** (TASK-23–25).

You **do** write design specs and token definitions under `docs/design/`.

You **do not** implement React/Next.js code or Python.

## Project Context

- **Parallel track C** — no code dependencies on TASK-13
- Branch: `task/TASK-26-ux-visual-spec` from `main`
- Commit format: `[AGENT_DESIGN] TASK-26: short description`
- API contract target: TASK-21 `GamePrediction` + `/health`

## Your Task

Deliver **mobile-first UX/visual spec** for MVP: daily slate, game detail, methodology/disclaimer layouts, data-freshness UX.

### Pages (minimum)

1. Daily slate — date picker, freshness banner, game cards
2. Game detail — predicted final, winner, win prob, member breakdown (collapsible)
3. Methodology + Disclaimer layout wireframes (copy from TASK-27)
4. Global header/footer chrome

### Visual direction

- Light-only v1 (dark mode out of scope)
- Sports-analytics aesthetic (not sportsbook)
- CSS custom properties: `--color-*`, `--font-*`, `--space-*`
- WCAG AA contrast, focus states

### Primary deliverable

`docs/design/mlb-slate-mvp-spec.md` — flows, wireframes, tokens, component inventory for TASK-23–25, out-of-scope v1 list.

## Exact Deliverables

| Path | Action |
|------|--------|
| `docs/design/mlb-slate-mvp-spec.md` | **Create** |
| `docs/design/assets/*` | Optional mocks |

## Off-Limits

- `web/` code (TASK-23)
- API (TASK-21)

## Git (worker)

- Commit on `task/TASK-26-ux-visual-spec`; do not push or open PR

## Definition of Done

- [ ] Spec covers slate, game detail, trust pages, global chrome
- [ ] Tokens ready for `web/styles/tokens.css`
- [ ] Committed on feature branch
- [ ] Handoff posted

## Handoff (required)

```text
Branch: task/TASK-26-ux-visual-spec
SHA: <commit>
Spec path: docs/design/mlb-slate-mvp-spec.md
Key decisions: light/dark, font, card density
Open questions for frontend: <list>
```
