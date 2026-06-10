# STANDARDS.md — gametime

> Read this file before writing any code.
> **EXISTING PATTERNS** = what the codebase does today. Match when modifying existing files.
> **FORWARD STANDARDS** = what new code should follow. Apply when creating new files.

---

## Who Reads This File

Code-writing agents: **AGENT_INFRA**, **AGENT_DATA**, **AGENT_BACKEND**

AGENT_QA may read it to verify compliance. Orchestrator and AGENT_CONTENT skip it.

---

## EXISTING PATTERNS

### Architecture

- **Sport config** drives CLI behavior (`sport: mlb` vs NBA in YAML).
- **MLB pregame** lives under `src/gametime/pregame/baseball/`: one module per ensemble member, shared `features.py` (`FEATURE_COLUMNS`), `ensemble.py` for blend/stack, `train.py` orchestrates member fit + val-only weight tuning.
- **Ingest sidecars** join to game rows via `attach_*` helpers in member modules or `features.py`; `has_*` flags indicate real vs fallback values.
- **Splits:** `train.common.split_table_by_season` — train 2021–2023, val 2024, test 2025 RS; weights and stacker fit on **val only**.
- **Production blend:** linear (`use_stacking: false` in `configs/mlb.yaml`).

### Component / Module Structure

```text
pregame/baseball/models/<member>.py   # class *Member, attach_* for features
ingest/mlb_*.py                       # download + parquet sidecars
pregame/baseball/train.py             # wires all members, writes ensemble.json
pregame/baseball/predict.py           # BaseballPregamePredictor inference
```

Members implement a common prediction protocol (`MemberPrediction` in `prediction.py`).

### Naming Conventions

- Python modules: `snake_case`
- Member registry keys match YAML `pregame.ensemble.members` (e.g. `travel_rest`, `park_factor`)
- Parquet paths declared in `configs/mlb.yaml` under `data.*_path`
- Test files: `tests/test_<area>.py`

### Data Flow

```text
gametime-download → raw/cache + processed/*.parquet
build_training_table(FEATURE_COLUMNS) → member preds → val fit_weights → ensemble.json
gametime-pregame / gametime-pregame-slate → predict.py → optional log parquet
```

No same-day leakage: retro slate backtest uses `game_date < slate_date`.

### Known Tech Debt

- README still describes stacking as production in one bullet — roadmap tracks fix (refactor proposal).
- Member errors highly correlated (75/78 test pairs r ≥ 0.94); new members must be orthogonal.
- Ensemble `pred_total` range narrow (~7.8–10.1); tail bias on `lt_7` / `gt_11` bands persists.
- `feature/mlb-ensemble-integration` branch referenced in archived docs — **obsolete**; use `main` only.

---

## FORWARD STANDARDS

### Architecture Principles

1. **One signal per window** — change ingest, one member, or blend rule per experiment.
2. **Val-only tuning** — never fit weights, stacker, or calibration on test 2025.
3. **FEATURE_COLUMNS discipline** — new game-level pregame columns → extend list + **retrain LGBM** in same PR.
4. **Decorrelation gate** — new members must have test total-error r < 0.94 vs every incumbent before merge.
5. **Document reality first** — holdout numbers from `pregame_summary.json`, not aspirational targets.

### Component / Module Design Rules

- New MLB member: `models/<name>.py` with `*Member` class + optional `attach_<name>`; register in `train.py`, `predict.py`, and `configs/mlb.yaml` `members` list.
- New ingest: module under `ingest/`, path keys in `configs/mlb.yaml`, load helper returning DataFrame keyed for join.
- Use `build_training_table` and existing attach patterns; do not duplicate split logic.

### Extensibility Patterns

#### How to add a new ensemble member

1. Ingest/features if needed (`has_*` real when populated).
2. `pregame/baseball/models/<member>.py` → `MemberPrediction`.
3. Extend `FEATURE_COLUMNS` if game-level signal; retrain LGBM.
4. Wire `train.py` + `predict.py` + `configs/mlb.yaml`.
5. Val-only refit `ensemble.json`; run full train.
6. `pytest tests/test_baseball_ensemble.py`; check decorrelation in `pregame_summary.json`.

#### How to add a new sidecar ingest

1. Add path/cache keys to `configs/mlb.yaml`.
2. Implement loader in `ingest/mlb_<name>.py`.
3. Hook into `gametime-download` pipeline (`pipeline.py` / `cli.py`).
4. Join in `features.py` via `attach_*`; set `has_*` column.

#### How to add a new CLI flag

1. Add argparse in `cli.py` for the relevant command.
2. Thread through predictor or download config dataclass.
3. Document in `docs/mlb_pregame_ops.md` if operator-facing.

#### How to add a new environment variable

1. Read via `os.environ` at CLI boundary only; never commit `.env`.
2. Document in task Handoff and ops doc if production-relevant.

### What Not To Do

- **No duplicate form heuristics** or XGB on same `FEATURE_COLUMNS` without decorrelation justification.
- **No test-set weight fitting.**
- **No faking `has_lineup=1`** when boxscore parse failed.
- **No direct commits to `main`.**
- **Do not enable `use_stacking: true`** in production without explicit product approval (winner% tradeoff).

### Dependency Rules

- Do not add new packages without listing them in the PR description.
- Prefer pybaseball / existing stack over new HTTP clients.
- MLB optional deps: `pip install -e '.[mlb]'` (`pybaseball`).

### Stack-Specific Rules

- Run `gametime-pregame-train --config configs/mlb.yaml` after any member or `FEATURE_COLUMNS` change.
- Production baseline (post-W10, test 2025): linear ensemble total MAE **3.615**, winner% **55.3%**.
- Daily ops: `gametime-download` → `gametime-pregame-slate --regular-season --decimals 2` (no retrain unless members change).
