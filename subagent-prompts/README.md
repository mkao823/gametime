# Subagent prompts

The orchestrator writes one file per dispatched task:

```text
subagent-prompts/TASK-XX-AGENT_ID.md
```

Workers read only their assigned prompt plus `agents.md`, `STANDARDS.md`, and task-specific code paths.

Historical worker prompts from the pre-reconcile era live in `_archived/pre-reconcile/docs/mlb_ensemble_roadmap.md` (reference only — do not execute).
