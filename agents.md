# agents.md — gametime

## Project Overview

**gametime** is a Python sports-prediction repo with two product tracks:

- **MLB pregame ensemble** (active) — 13-member ensemble predicting total runs and home margin; linear blend at inference; val 2024 / test 2025 holdout discipline.
- **NBA** — in-game total model, pregame (Elo/LGBM), live inference, signals. Season ending; maintenance only near-term.

Workflow is governed by `orchestrator-prompt.md` (backlog), `STANDARDS.md` (code patterns), and `docs/mlb_pregame_ops.md` (daily MLB ops). Worker dispatch prompts live in `subagent-prompts/`.

---

## Tech Stack

| Layer | Choice | Why / Notes |
|---|---|---|
| Language | Python ≥3.9 | `pyproject.toml` |
| ML | LightGBM, scikit-learn (Ridge stacker) | LGBM member + optional stacking at train |
| Data | pandas, pyarrow | Parquet sidecars and game logs |
| MLB ingest | pybaseball, MLB Stats API | Hybrid `games.parquet` + sidecars |
| Config | YAML (`configs/mlb.yaml`, `configs/default.yaml`) | Sport-specific paths and ensemble members |
| CLI | setuptools entry points | `gametime-pregame-train`, `gametime-download`, etc. |
| Tests | pytest | `tests/test_baseball_ensemble.py` and sport-specific suites |

> **Total cost:** Local/dev only; MLB Stats API and Open-Meteo are free tiers.

---

## Repo Layout

```text
agents.md / STANDARDS.md / orchestrator-prompt.md   # agent workflow (SSOT)
subagent-prompts/                                    # per-task worker prompts
docs/
  mlb_ensemble_roadmap.md                            # slim MLB reference (constraints, baseline)
  mlb_pregame_ops.md                                 # daily download / slate / backtest
_archived/pre-reconcile/                             # retired workflow docs (do not use for tasks)
configs/
  mlb.yaml                                           # MLB ensemble production config
  default.yaml                                       # NBA config
src/gametime/
  pregame/baseball/                                  # MLB ensemble (members, train, predict)
  pregame/                                           # shared pregame + NBA pregame
  ingest/                                            # MLB/NBA data ingest
  live/                                              # NBA in-game
  cli.py                                             # all console entry points
models/mlb/pregame/                                  # trained artifacts (ensemble.json, LGBM txt)
data/mlb/processed/                                  # games.parquet, sidecars
reports/mlb/eval/                                    # pregame_summary.json, backtest outputs
tests/
```

---

## Off-Limits Areas

None stated — use judgment. Do not modify trained artifacts under `models/mlb/pregame/` or bulk `data/` without explicit human approval. Code refactors outside task scope belong in `docs/mlb_ensemble_roadmap.md` → Refactor proposals, not drive-by PRs.

---

## Agent Roles

### 🧠 Orchestrator Agent

Reads `agents.md`, `STANDARDS.md`, and `orchestrator-prompt.md` every session. Decomposes epics into tasks, writes subagent prompts into `subagent-prompts/`, tracks the task board, and reviews deliverables. Does **not** write application code or content directly.

When writing prompts for code-writing agents, always include: **"Read STANDARDS.md before writing any code."**

### 👷 Worker Agents

| Agent ID | Role | Responsibilities | Reads STANDARDS.md |
|---|---|---|---|
| AGENT_INFRA | Infra / CLI / config | Entry points, YAML config, ops wiring, pytest CI hygiene | Yes |
| AGENT_DATA | Data ingest | `ingest/mlb*.py`, sidecars, Stats API / pybaseball / Statcast pulls | Yes |
| AGENT_BACKEND | ML / ensemble | Members, `train.py`, `ensemble.py`, `predict.py`, features | Yes |
| AGENT_QA | Eval / gates | Holdout reports, decorrelation audit, slate backtest verification | Optional |

AGENT_FRONTEND, AGENT_DESIGN, AGENT_AUTH, AGENT_CONTENT, AGENT_SEO — not used (no UI product).

---

## Inter-Agent Dependencies

```text
AGENT_DATA (ingest / sidecars)
    └── AGENT_BACKEND (FEATURE_COLUMNS + member + LGBM retrain)
            └── AGENT_INFRA (config / CLI if new flags)
                    └── AGENT_QA (train + decorrelation gate + pytest)
```

NBA maintenance tasks are independent of the MLB chain unless shared `pregame/` code changes.

---

## Shared Conventions

- **Branch strategy:** `task/TASK-XX-short-desc` from `main`; merge PR to `main` (no integration branch).
- **Commit format:** `[AGENT_ID] TASK-XX: short description`
- **File naming:** snake_case modules under `src/gametime/`; members in `pregame/baseball/models/<name>.py`
- **Env variables:** never committed; `ODDS_API_KEY` only if W15 market unblocks
- **Subagent prompts:** `subagent-prompts/TASK-XX-AGENT_ID.md` before running a worker
- **Standards:** AGENT_INFRA, AGENT_DATA, AGENT_BACKEND must read `STANDARDS.md` before writing code
- **MLB authority:** `docs/mlb_ensemble_roadmap.md` for decorrelation gate, baseline metrics, refactor proposals
- **MLB ops:** `docs/mlb_pregame_ops.md` for download / slate / backtest commands

---

## Definition of Done (per task)

- [ ] Code committed on feature branch with PR opened against `main`
- [ ] `pytest` relevant suites pass (`tests/test_baseball_ensemble.py` minimum for MLB member work)
- [ ] `gametime-pregame-train --config configs/mlb.yaml` completes when members/features change
- [ ] Holdout metrics in `reports/mlb/eval/pregame_summary.json` documented in Handoff
- [ ] New members: decorrelation gate passed (test total-error r < 0.94 vs **all** incumbents)
- [ ] Orchestrator has reviewed and marked task done in the task board
