# MLB pregame ensemble — reference (June 2026)

Slim reference for constraints and baseline. **Backlog and task board:** `orchestrator-prompt.md`. **Worker prompts:** `subagent-prompts/`. **Daily ops:** `mlb_pregame_ops.md`.

Archived full roadmap + R1 research doc: `_archived/pre-reconcile/`.

---

## Current state

| Field | Value |
|-------|-------|
| Branch | `main` @ c7eac06 (W10 SP/lineup backfill) |
| Members | 13 — see `configs/mlb.yaml` `pregame.ensemble.members` |
| Blend | Linear (`use_stacking: false`) |
| Total calibration | Off (`total_enabled: false`) |
| Splits | Train 2021–2023 / val 2024 / test 2025 RS |
| Data freshness | `games.parquet` through **2026-06-08** |

### Holdout baseline (test 2025, post-W10)

| Metric | Value |
|--------|-------|
| Linear ensemble total MAE | **3.615** |
| Linear ensemble margin MAE | 3.504 |
| Linear ensemble winner% | **55.3%** |
| `has_lineup_frac_train` | 1.0 |
| `has_lineup_frac_test` | 0.932 |
| `has_starting_pitcher_frac` | 0.982 |

Stacking beats linear on total MAE (~0.03) but loses ~1.8 pp winner% — production stays linear.

---

## Decorrelation gate

On **2025 test** total errors: **75/78** member pairs with Pearson **r ≥ 0.94**.

**Merge sign-off for new members:** test total-error **r < 0.94** vs **every** incumbent.

Known hub (post-W10): `pitcher` × `travel_rest` ~0.998.

---

## Git workflow

```bash
git fetch origin && git checkout main && git pull origin main
git checkout -b task/TASK-XX-short-desc
# work → commit → PR to main
```

- One branch per task from `main`
- Commit: `[AGENT_ID] TASK-XX: short description`
- Do not push or open PR unless the human asks

---

## Member iteration checklist

1. Ingest / features (no leakage; `has_*` real when populated)
2. `models/<member>.py` → `MemberPrediction`
3. Extend `FEATURE_COLUMNS` + retrain LGBM if new game-level columns
4. Wire `train.py`, `predict.py`, `configs/mlb.yaml`
5. Val-only refit `ensemble.json`
6. `pytest tests/test_baseball_ensemble.py` + `gametime-pregame-train`
7. Decorrelation audit in `pregame_summary.json`
8. Handoff with val + test metrics

---

## Window glossary

| Window | Task ID | Status | Notes |
|--------|---------|--------|-------|
| W10 SP/lineup backfill | TASK-12 | ✅ done | P1; `has_lineup_frac_train=1.0` |
| W11 bullpen fatigue v1 | — | ❌ cancelled | P2; r 0.997 vs `lgbm`; not merged |
| W11 bullpen v2 | TASK-17 | optional | LGBM without pen cols + orthogonal redesign |
| W12 Statcast offense | TASK-13 | **next** | P3; orthogonal signal |
| W13 lineup platoon v2 | TASK-14 | todo | P7 |
| W14 quantile total | TASK-15 | todo | P8 meta |
| W15 market closing | TASK-16 | blocked | P4; no odds source |
| W20 context stack | — | ❌ cancelled | Never scoped — was informal placeholder only |

---

## Known constraints

- Ensemble `pred_total` range narrow (~7.8–10.1 on test); tail bias (`lt_7` +4.56, `gt_11` −6.22)
- Do **not** add duplicate form heuristics or XGB without decorrelation justification
- Do **not** fake confirmed lineups when boxscore parse fails

---

## Refactor proposals

> Code/doc fixes outside active tasks — pick up as dedicated TASK-XX when prioritized.

| ID | Proposal | Rationale |
|----|----------|-----------|
| RF-01 | Fix README blend bullet | README §MLB still says "Ridge stacking (production)" with `use_stacking: true`; config uses linear |
| RF-02 | Align `features.py` FEATURE_ROADMAP comments | Point to `orchestrator-prompt.md` / TASK IDs instead of archived research doc paths |
| RF-03 | Pre-W10 metric strings in `mlb_pregame_ops.md` | Ops doc cites 55.7% / 3.609 in one W6-eval paragraph — update to 55.3% / 3.615 when touched |

---

## Commands

```bash
pip install -e '.[mlb]'
gametime-download --config configs/mlb.yaml
gametime-pregame-train --config configs/mlb.yaml
gametime-pregame-slate --config configs/mlb.yaml --date $(date +%Y-%m-%d) --regular-season --decimals 2
gametime-pregame-slate-backtest --config configs/mlb.yaml --days 14 --regular-season
```

See `mlb_pregame_ops.md` for full operator workflow.
