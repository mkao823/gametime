# AGENT_DATA — TASK-13: W12 Statcast offense (P3)

## Your Role

You are **AGENT_DATA**. You own MLB ingest, sidecar parquet, download-pipeline hooks, and feature attachment for new data sources.

You **do** implement ingest modules, config keys, `attach_*` joins, `FEATURE_COLUMNS` extensions, and (optionally) a simple heuristic ensemble member when decorrelation passes.

You **do not** redesign the blend/stacker, enable `use_stacking: true`, touch NBA code, or modify trained artifacts under `models/mlb/pregame/` directly (retrain via CLI only).

## Project Context

- Project: gametime — MLB pregame ensemble on `main` @ c7eac06 (post-W10)
- Stack: Python, pybaseball, pandas/parquet, YAML config
- Branch: `task/TASK-13-w12-statcast-offense` from `main`
- Commit format: `[AGENT_DATA] TASK-13: short description`
- Production baseline (test 2025): linear ensemble total MAE **3.615**, winner% **55.3%**
- Decorrelation gate: any **new** member must have test total-error Pearson **r < 0.94** vs **every** incumbent (13 members today)

## Inputs Available

- Read `agents.md`, `STANDARDS.md`, `docs/mlb_ensemble_roadmap.md`, `docs/mlb_pregame_ops.md`
- **Read STANDARDS.md before writing any code.** Existing Patterns for existing files; Forward Standards for new files.
- Reference patterns:
  - Ingest: `src/gametime/ingest/mlb_lineup.py` (sidecar schema, cache dir, `download_*` / `load_*`)
  - Pipeline hook: `src/gametime/pipeline.py` (`_sidecar_needs_train_backfill`, `needs_lineup` block)
  - Attach + member: `src/gametime/pregame/baseball/models/lineup.py`
  - Rolling no-leakage: `src/gametime/pregame/baseball/models/runs_strength.py` (`shift(1)` rolling)
- R1 P3 spec (archived reference): `_archived/pre-reconcile/docs/mlb_ensemble_research_backlog.md` § P3

## Your Task

Ship **W12 — Statcast team expected offense**: team-level rolling contact-quality metrics joined to pregame game rows, exposed in `FEATURE_COLUMNS`, with LGBM retrained. Optionally add a `statcast_offense` heuristic member **only if** it passes the decorrelation gate.

### Signal (P3)

Per team, prior to each game (no same-day leakage):

| Metric | Notes |
|--------|--------|
| Rolling **xwOBA** | Primary true-talent offense proxy |
| Rolling **barrel%** | Contact quality |
| Rolling **hard-hit%** | Contact quality (avg exit velo optional if readily available) |

- Source: Baseball Savant via **pybaseball** (prefer existing stack; document any new API surface in PR description).
- Availability: Statcast batting aggregates 2015+; align `min_season` with `train.train_seasons` earliest year (**2021**).
- Leakage discipline: aggregate to **team-date**, then apply **shift(1)** rolling windows (default window **30** days or **~150 PA** equivalent — pick one, document in module docstring). No same-game Statcast in features.
- Join key: `(team, game_date)` → game-level `home_*` / `away_*` columns on `game_id`.
- `has_statcast_offense=1` when real Statcast-backed rolling values exist; `0` with league-average fallbacks otherwise (never fake `1`).

### Caching / rate limits

Follow `mlb_lineup.py` / `mlb_pitchers.py` cache patterns:

- Cache raw pulls under `data/mlb/raw/statcast_offense/` (configurable).
- Prefer **daily team batting aggregates** over per-pitch pulls; incremental download on `gametime-download`.
- Respect pybaseball rate limits (`time.sleep`, disk cache, idempotent rebuild).

### Feature columns (required)

Extend `FEATURE_COLUMNS` in `src/gametime/pregame/baseball/features.py` with game-level offense-quality columns, e.g.:

- `home_xwoba_roll`, `away_xwoba_roll`
- `home_barrel_pct_roll`, `away_barrel_pct_roll`
- `home_hard_hit_pct_roll`, `away_hard_hit_pct_roll`
- `xwoba_off_diff` (home − away)
- `has_statcast_offense`

Use league-average defaults in `build_training_table` fallbacks when sidecar missing (mirror `has_lineup` / `has_weather` patterns).

### Optional member: `statcast_offense`

If solo member errors are decorrelated (r < 0.94 vs all incumbents on **test 2025** total errors):

1. Add `src/gametime/pregame/baseball/models/statcast_offense.py` with `StatcastOffenseMember` + `attach_statcast_offense`.
2. Register in `train.py`, `predict.py`, and `configs/mlb.yaml` `pregame.ensemble.members`.
3. Heuristic should map xwOBA/barrel spread → total + margin (orthogonal to `runs_strength` / `poisson` — target r < 0.92 vs those per P3 hypothesis).

**If decorrelation fails:** ship ingest + features + LGBM retrain **without** adding the member to the ensemble. Document failure in Handoff.

## Exact Deliverables

| Path | Action |
|------|--------|
| `src/gametime/ingest/mlb_statcast_offense.py` | **Create** — build/download/load sidecar; `STATCAST_OFFENSE_COLUMNS` constant |
| `configs/mlb.yaml` | **Modify** — `statcast_offense_games_path`, `statcast_offense_cache_dir`, `statcast_offense_min_season`, `refresh_statcast_offense_games`, optional `statcast_offense_max_dates` dev smoke |
| `src/gametime/pipeline.py` | **Modify** — download hook with `_sidecar_needs_train_backfill` on `has_statcast_offense` |
| `src/gametime/cli.py` | **Modify** — thread `statcast_offense_games_path` through train/predict/slate/backtest (mirror `lineup_games_path`) |
| `src/gametime/pregame/baseball/features.py` | **Modify** — `FEATURE_COLUMNS`, fallbacks, FEATURE_ROADMAP comment (W12 shipped) |
| `src/gametime/pregame/baseball/models/statcast_offense.py` | **Create** (optional member) — `attach_statcast_offense` |
| `src/gametime/pregame/baseball/train.py` | **Modify** — load sidecar, attach, optional member fit |
| `src/gametime/pregame/baseball/predict.py` | **Modify** — load sidecar, attach, optional member predict |
| `src/gametime/pregame/baseball/slate_backtest.py` | **Modify** — history filter for statcast sidecar if needed (mirror lineup) |
| `configs/mlb.yaml` `pregame.ensemble.members` | **Modify** only if optional member passes gate |
| `tests/test_baseball_ensemble.py` | **Modify** — unit tests for attach logic, rolling shift(1), `has_statcast_offense` (no network) |
| `docs/mlb_pregame_ops.md` | **Modify** — brief W12 download/backfill note when config keys added |

**Output artifact:** `data/mlb/processed/statcast_offense_games.parquet` (game-level sidecar; not committed to git).

## Off-Limits

- Do not commit `data/mlb/**`, `models/mlb/pregame/**`, or `.env`
- Do not enable `use_stacking: true` or `calibration.total_enabled: true`
- Do not add XGBoost or duplicate form-heuristic members
- Do not fit ensemble weights on test 2025
- Do not push or open PR unless the human asks
- Do not touch NBA ingest/config

## Git (worker)

- Commit on `task/TASK-13-w12-statcast-offense` when verify passes
- **Do not** push, open PR, or merge — orchestrator handles that after Handoff

## Definition of Done

- [ ] `pytest tests/test_baseball_ensemble.py -q` passes (add focused tests for new attach/ingest helpers)
- [ ] `gametime-download --config configs/mlb.yaml` builds/refreshes statcast sidecar (smoke with `statcast_offense_max_dates` if needed locally)
- [ ] Train-season `has_statcast_offense` coverage ≥ `sidecar_train_min_frac` (0.85) for 2021–2023 RS rows, or document gap + fallback behavior
- [ ] `gametime-pregame-train --config configs/mlb.yaml` completes (LGBM retrained on extended `FEATURE_COLUMNS`)
- [ ] `reports/mlb/eval/pregame_summary.json` updated with val + test metrics
- [ ] If optional member shipped: decorrelation table shows r < 0.94 vs **all** incumbents on test total errors
- [ ] Code **committed** on feature branch (not pushed)

## Handoff (required)

```text
Branch: task/TASK-13-w12-statcast-offense
SHA: <commit>
Member shipped: yes/no (statcast_offense)
Sidecar: path, rows, has_statcast_offense frac (train / val / test)
Val 2024: total MAE, margin MAE, winner%
Test 2025: total MAE, margin MAE, winner% (compare to baseline 3.615 / 55.3%)
Decorrelation: max r vs incumbent (if member shipped) or N/A
Pred total σ on test (baseline ensemble ~narrow; P3 target σ > 0.35 if member helps)
Notes: cache strategy, rate-limit handling, any train-season gaps
```
