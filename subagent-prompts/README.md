# Subagent prompts

The orchestrator writes one file per dispatched task:

```text
subagent-prompts/TASK-XX-AGENT_ID.md
```

Workers read only their assigned prompt plus `agents.md`, `STANDARDS.md`, and task-specific code paths.

## Active prompts (June 2026)

| File | Task | Status |
|------|------|--------|
| `TASK-13-AGENT_DATA.md` | W12 Statcast offense | model track |
| `TASK-21-AGENT_INFRA.md` | Predictions API v1 | PR #12 |
| `TASK-23-AGENT_FRONTEND.md` | App shell | PR #14 |
| `TASK-24-AGENT_FRONTEND.md` | Daily slate page | **dispatch now** |
| `TASK-26-AGENT_DESIGN.md` | UX/visual spec | PR #11 |
| `TASK-27-AGENT_CONTENT.md` | Methodology + trust | PR #10 |

**Commit prompts with task branches** so they are not lost — orchestrator should verify `subagent-prompts/TASK-XX-*.md` is included in the task PR or a follow-up docs commit.

Historical worker prompts from the pre-reconcile era live in `_archived/pre-reconcile/docs/mlb_ensemble_roadmap.md` (reference only — do not execute).
