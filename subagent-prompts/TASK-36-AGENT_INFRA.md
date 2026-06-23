# AGENT_INFRA — TASK-36: Daily MLB refresh automation wrapper + observability markers

## Your Role
You are **AGENT_INFRA**. You own CLI/config/ops wiring for safe daily automation.

You **do** create a scheduler-safe refresh command profile and explicit success/failure signals.

You **do not** change MLB model behavior, member logic, or prediction calculations.

## Project Context
- Project: `gametime` (MLB pregame ensemble)
- Branch: `task/TASK-36-daily-refresh-ops-wrapper` from `main`
- Commit format: `[AGENT_INFRA] TASK-36: short description`
- Read `agents.md`, `STANDARDS.md`, `orchestrator-prompt.md`, and `docs/mlb_pregame_ops.md`
- **Read STANDARDS.md before writing any code.**

## Problem To Solve
Daily runs need clear automation semantics:
- fast default routine (no unnecessary historical rebuild)
- explicit success/failure exit codes
- machine-readable success markers
- freshness checks and duration visibility
- rollback/fallback when refresh partially fails

Current operator flow relies on generic `gametime-download` output and can feel stuck during long work.

## Dependencies
- TASK-35 defines daily incremental ingest behavior.
- You may proceed now but integrate with TASK-35’s finalized daily mode switch before handoff.

## Orchestrator Decisions (locked)
1. Keep normal daily mode incremental and lightweight; full rebuild remains manual/periodic.
2. No changes to prediction outputs or blend behavior.
3. Add explicit markers/health signals for scheduler automation.
4. On partial failure: preserve last known-good processed files and write failure marker with reason.
5. Keep implementation minimal and localized (CLI/pipeline/docs/tests).

## Your Task

### 1) Add operator-facing refresh modes
- Add clear refresh modes (or equivalent flags/profile) for:
  - `daily` (incremental, fast, automation default)
  - `manual` (operator-triggered; can mirror daily or full via explicit choice)
  - `backfill/full` (heavy historical rebuild, unscheduled)
- Wire mode selection through CLI boundary (likely `src/gametime/cli.py`) into pipeline flow.
- Preserve backward compatibility for existing `gametime-download --config ...` usage.

### 2) Add success/failure markers and duration reporting
- Emit structured run metadata at end of refresh:
  - status (`success` / `failed`)
  - mode
  - started_at / finished_at
  - elapsed_seconds
  - games_max_date (or equivalent freshness anchor)
- Write machine-readable marker files under a stable location (for cron/scheduler checks), e.g. under `reports/mlb/ops/` or similar existing pattern.
- Ensure non-zero exit on failed refresh mode execution.

### 3) Rollback/fallback behavior on partial failure
- Implement safe write behavior so failed refresh does not corrupt last known-good artifacts:
  - write to temp path then atomic replace for key parquet outputs, or
  - preserve prior file and only swap on successful completion.
- On partial failure, leave prior successful data in place and record failure marker with stage + error context.

### 4) Freshness check surface
- Add a lightweight freshness-check path suitable for scheduler probes:
  - verify `games.parquet` max date is within acceptable lag window (configurable threshold)
  - return clear pass/fail signal and message for automation
- Can be a CLI subcommand/flag or documented script wrapper, but must be testable and deterministic.

### 5) Tests + docs
- Add/extend tests for:
  - mode routing (`daily`/`backfill`)
  - marker file creation and content
  - failure path preserves last known-good files
  - freshness check pass/fail behavior and exit code
- Update `docs/mlb_pregame_ops.md` with concise operator snippets for daily/manual/backfill and marker checks.

## Exact Deliverables
- `src/gametime/cli.py` (mode/freshness command surface)
- `src/gametime/pipeline.py` (mode wiring + run metadata + failure semantics)
- Small new helper module(s) under existing package paths if needed (no new `src/gametime/data` package)
- `docs/mlb_pregame_ops.md` updates for scheduler-safe routine
- `tests/test_*.py` updates for mode/marker/freshness behavior

## Off-Limits
- No ensemble/model logic changes
- No frontend/web changes
- No secret handling changes
- No broad refactors outside refresh flow

## Definition of Done
- [ ] Daily mode command completes with explicit success/failure and elapsed duration output
- [ ] Success/failure marker files are written with machine-readable fields
- [ ] Failure path preserves prior known-good processed artifacts
- [ ] Freshness check command/flow returns deterministic pass/fail and correct exit code
- [ ] `docs/mlb_pregame_ops.md` includes daily/manual/backfill operator snippets
- [ ] Relevant tests pass and are listed in handoff
- [ ] Changes committed on task branch with required commit message format

## Handoff Required
Provide:
1. Branch and commit SHA
2. New/updated CLI commands (copy-paste examples)
3. Marker file location + example JSON payloads (success + failure)
4. Freshness check behavior and threshold configuration
5. Partial-failure rollback behavior summary
6. Test commands + pass output
