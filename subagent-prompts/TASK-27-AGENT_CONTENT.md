# AGENT_CONTENT — TASK-27: Methodology + trust pages

## Your Role

You are **AGENT_CONTENT**. You write user-facing copy for trust, methodology, and legal disclaimers.

You **do** produce accurate markdown grounded in how the repo works.

You **do not** implement React pages or change model code.

## Project Context

- **Parallel track C**
- Branch: `task/TASK-27-methodology-trust-content` from `main`
- Commit format: `[AGENT_CONTENT] TASK-27: short description`
- Baseline metrics: test 2025 total MAE **3.615**, winner% **55.3%**
- Production blend: linear (`use_stacking: false`)

## Your Task

Write methodology and disclaimer content for the web product.

### Required files

| File | Purpose |
|------|---------|
| `web/content/methodology.md` | Ensemble approach, data sources, holdout discipline, metrics, limitations |
| `web/content/disclaimer.md` | Not gambling advice, no warranty, responsible gambling, jurisdiction, no affiliation |
| `web/content/about.md` | Short product mission |
| `web/content/README.md` | Index + frontmatter notes for TASK-23 |

### Accuracy rules

- 13 members from `configs/mlb.yaml` (verify at Handoff)
- Cite only documented holdout metrics
- Do not claim ROI or beat-the-market
- Do not describe Ridge stacking as production

## Off-Limits

- React implementation
- Fabricated metrics

## Git (worker)

- Commit on `task/TASK-27-methodology-trust-content`; do not push or open PR

## Definition of Done

- [ ] Copy matches repo behavior
- [ ] Disclaimer suitable for legal review pre-launch
- [ ] Committed on feature branch
- [ ] Handoff posted

## Handoff (required)

```text
Branch: task/TASK-27-methodology-trust-content
SHA: <commit>
Files: web/content/*.md
Member count cited: <N>
Metrics cited: test 2025 MAE / winner%
Review flags: <legal/product items>
```
