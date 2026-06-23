# AGENT_DATA — TASK-35: Lightweight daily MLB refresh ingest + pybaseball hardening

## Your Role
You are **AGENT_DATA**. You are responsible for MLB ingest reliability and incremental data-refresh behavior.

You **do** implement a lighter daily refresh path that updates recent dates without forcing full historical rebuild work in normal automation.

You **do not** change ensemble modeling, prediction math, or frontend/API response contracts.

## Project Context
- Project: `gametime` (MLB pregame ensemble on `main`)
- Branch: `task/TASK-35-daily-refresh-ingest` from `main`
- Commit format: `[AGENT_DATA] TASK-35: short description`
- Read `agents.md`, `STANDARDS.md`, `orchestrator-prompt.md`, and `docs/mlb_pregame_ops.md`
- **Read STANDARDS.md before writing any code.**

## Problem To Solve
Current `gametime-download --config configs/mlb.yaml` can be heavy and mostly silent for daily runs. pybaseball season pulls sometimes include `"Unknown"` in run columns and log repetitive errors like:

`[mlb] skip NYM 2026: could not convert string to float: 'Unknown'`

Daily automation needs an incremental mode that is fast, robust to these row-level anomalies, and emits heartbeat logs while long loops are running.

## Orchestrator Decisions (locked)
1. Keep existing MLB prediction behavior unchanged.
2. Add a daily-safe ingest profile that avoids full historical rebuilds during routine scheduled runs.
3. Preserve full/backfill capability separately for periodic maintenance.
4. `"Unknown"` run values should be treated as non-final/unusable rows and skipped at row level, not as a team-season failure.
5. Add periodic progress logs (heartbeat) during long loops so operators can tell the process is alive.

## Your Task

### 1) Incremental daily ingest path in MLB download flow
- Extend MLB ingest path (likely in `src/gametime/ingest/mlb.py` and/or `src/gametime/pipeline.py`) to support a daily incremental mode.
- Daily incremental mode should:
  - Prioritize recent-day refresh (Stats API backfill window and recent sidecar windows).
  - Avoid expensive historical rebuild work unless required (missing artifact, explicit full/backfill mode, or explicit refresh flag).
  - Reuse existing config and path structure under `configs/mlb.yaml` and `data/mlb/...`.
- Keep implementation localized; do not introduce a new cross-module package like `src/gametime/data` for MLB.

### 2) pybaseball Unknown-value hardening
- Update row parsing so `"Unknown"` (or equivalent non-numeric placeholders) in run fields does not raise and abort the whole team/season fetch.
- Skip only invalid/non-final rows and continue processing valid rows from that team/season.
- Keep informative logs for skipped invalid rows without flooding output.

### 3) Long-run heartbeat/progress logs
- Add periodic progress logs in long loops (team-season loops and similar) with clear counters, for example:
  - season/team progress
  - rows accepted/skipped
  - elapsed seconds checkpoint
- Keep logs concise and scheduler-friendly.

### 4) Tests
- Add/extend tests to cover:
  - Unknown/non-numeric run values are safely skipped without failing full team-season processing.
  - Daily incremental mode uses lighter refresh behavior than full mode.
  - Heartbeat/progress logging appears for long iterations (assert via captured logs or mocked logger/print).

## Exact Deliverables
- `src/gametime/ingest/mlb.py` (incremental mode support + parse hardening + heartbeat hooks)
- `src/gametime/pipeline.py` (thread daily-vs-full ingest behavior through MLB download)
- `tests/test_*.py` updates/additions for ingest reliability and mode behavior
- If config keys are needed, minimal updates in `configs/mlb.yaml` with backward-compatible defaults

## Off-Limits
- No model-member changes under `src/gametime/pregame/baseball/models/`
- No changes to prediction blend behavior or `ensemble.json`
- No frontend or web app changes
- No secrets or credentials in repo

## Definition of Done
- [ ] `gametime-download --config configs/mlb.yaml` still works in default/full behavior
- [ ] New daily incremental mode runs without triggering full historical rebuild in normal conditions
- [ ] Unknown pybaseball run values no longer cause team-season abort logs of float-conversion exceptions
- [ ] Heartbeat/progress logs emitted during long loops
- [ ] Relevant MLB ingest tests pass (`pytest` target list included in handoff)
- [ ] Changes are committed on task branch with required commit format

## Handoff Required
Provide:
1. Branch and commit SHA
2. Files changed
3. Exact CLI/config switch for daily incremental mode
4. Before/after sample logs showing Unknown-value handling and heartbeat output
5. Test command(s) and results
6. Any caveats for TASK-36 automation wiring
