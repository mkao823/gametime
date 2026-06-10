# Web content (TASK-27)

Markdown source for trust, methodology, and legal pages. **AGENT_FRONTEND (TASK-23/24)** renders these files in the public MLB slate app.

## Files

| File | Route (suggested) | Purpose |
|------|-------------------|---------|
| `methodology.md` | `/methodology` | How predictions are built, data sources, holdout metrics, limitations |
| `disclaimer.md` | `/disclaimer` | Not gambling advice, no warranty, responsible gambling, jurisdiction |
| `about.md` | `/about` | Short product mission |

## Frontmatter (optional YAML)

Each page may include a YAML block at the top for future SEO (TASK-35):

```yaml
---
title: Page title
description: One-line summary for meta description / Open Graph
---
```

Fields in use today:

- **`title`** — Human-readable page title (can override the first `#` heading in layout).
- **`description`** — Short blurb for `<meta name="description">` and social cards.

TASK-23 should parse frontmatter if present; body is standard Markdown (tables, links, headings).

## Accuracy constraints for editors

- Cite holdout metrics only from `docs/mlb_ensemble_roadmap.md` / `orchestrator-prompt.md` baseline (currently test 2025: total MAE **3.615**, winner **55.3%**).
- Member count: verify `configs/mlb.yaml` → `pregame.ensemble.members` (currently **13**).
- Production blend is **linear** (`use_stacking: false`); do not describe Ridge stacking as production.
- Do not claim ROI or beat-the-market without TASK-16 market edge work.

## Related docs

- Design layout: `docs/design/mlb-slate-mvp-spec.md` (TASK-26)
- Ops: `docs/mlb_pregame_ops.md`
- Roadmap / baseline: `docs/mlb_ensemble_roadmap.md`
