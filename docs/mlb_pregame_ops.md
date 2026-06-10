# MLB pregame operations

Production workflow for the MLB pregame ensemble (see `configs/mlb.yaml` `pregame.ensemble.members`). No `ODDS_API_KEY` required.

## Setup

```bash
pip install -e '.[mlb]'   # pybaseball for download + slate discovery
```

If console scripts are not on `PATH`:

```bash
export PYTHONPATH=src
python3 -m gametime.cli <command> ...
```

## Data refresh

`configs/mlb.yaml` lists `data.seasons` through the current MLB year so form/Elo/Poisson see recent results.

### Hybrid `games.parquet` (pybaseball + MLB Stats API)

| Step | What happens |
|------|----------------|
| 1 | **pybaseball** rebuilds bulk game logs (Baseball Reference team schedules). |
| 2 | **MLB Stats API** backfills any **Final** dates still missing through yesterday (fixes 1–3 day BR lag). |

Config (after [W6-statsapi-games](mlb_ensemble_roadmap.md#w6-statsapi-games--copy-paste-worker-prompt) ships):

| Key | Default | Meaning |
|-----|---------|---------|
| `games_statsapi_backfill_days` | `14` | Re-pull last N calendar days from Stats API each download |
| `games_statsapi_game_types` | `[R]` | Regular-season finals |
| `games_statsapi_postseason_enabled` | `false` | Set **`true` in October** for playoff game ingest |
| `games_statsapi_postseason_types` | `[P, F, W, D, L]` | Postseason `gameType` codes when enabled |

**Playoffs:** Before playoff slates, set `games_statsapi_postseason_enabled: true`, run `gametime-download`, and use `gametime-pregame` / slate **without** `--regular-season` (or equivalent `is_playoff`). Until then, incremental ingest is RS-only.

```bash
gametime-download --config configs/mlb.yaml
```

**W10 sidecar backfill (2021+ train seasons):** `pitcher_min_season` and `lineup_min_season` default to **2021** (earliest `train.train_seasons`). On download, if train-season coverage for `has_starting_pitcher` or `has_lineup` falls below `sidecar_train_min_frac` (default **0.85**), the corresponding sidecar is rebuilt from MLB Stats API boxscores (cached under `data/mlb/raw/pitcher_boxscores`). Force a full refresh with `refresh_pitcher_games: true` / `refresh_lineup_games: true` in config. For dev smoke tests only, set `pitcher_max_dates` / `lineup_max_dates` to limit API dates. Games without parseable boxscore lineups keep `has_lineup=0` and team wOBA proxy values — never faked as confirmed lineups.

**W12 Statcast offense sidecar:** `statcast_offense_min_season` defaults to **2021**. Daily team batting aggregates are pulled via pybaseball `statcast` (cached under `data/mlb/raw/statcast_offense/`) and rolled with **shift(1) + 30-day** windows. Rebuild when train-season `has_statcast_offense` coverage falls below `sidecar_train_min_frac`, or set `refresh_statcast_offense_games: true`. Dev smoke: `statcast_offense_max_dates`. Games without sufficient prior Statcast PA keep `has_statcast_offense=0` and league-average fallbacks.

Confirm processed games include yesterday:

```bash
python3 -c "
import pandas as pd
g = pd.read_parquet('data/mlb/processed/games.parquet')
g['game_date'] = pd.to_datetime(g['game_date'])
print('rows', len(g), 'max_date', g['game_date'].max().date())
"
```

If `max_date` is more than one day behind, slate preds will not update day-over-day (stale form/Elo). Re-run download after W6-statsapi-games is merged, or check pybaseball/Stats API availability.

## Train artifacts

Run when `models/mlb/pregame/ensemble.json` is missing or after member/weight changes:

```bash
gametime-pregame-train --config configs/mlb.yaml
```

Artifacts: `models/mlb/pregame/ensemble.json`, `meta.json`, `lgbm_*.txt`, eval under `reports/mlb/eval/`.

Member list in config must match `pregame.ensemble.members` (13 members as of W6-eval refresh).

**Eval splits:** `train.val_season` (default 2024 RS) is used to tune ensemble weights and the Ridge stacker; `train.test_seasons` (default `[2025]` RS) is report-only holdout. After changing either season in `configs/mlb.yaml`, re-run `gametime-pregame-train` and check `reports/mlb/eval/pregame_summary.json` (`val_season`, `test_seasons`, and per-split metrics). See [W6-eval](mlb_ensemble_roadmap.md#w6-eval--holdout-splits-recommended) in the ensemble roadmap.

## Blend mode

`pregame.ensemble.use_stacking` selects how member predictions are combined at inference:

| Mode | Config | Behavior |
|------|--------|----------|
| **Linear** (weighted average) | `use_stacking: false` | Uses `weights` in `ensemble.json` |
| **Stacked** (Ridge meta-learner) | `use_stacking: true` | Uses `stacker` in `ensemble.json` (fit on val only) |

Production default is **linear** (`use_stacking: false`). **W6-eval 13-member holdout (2025 test):** `ensemble_stacked` beats linear `ensemble` on total MAE (3.582 vs 3.609) and margin MAE (3.500 vs 3.505) but **loses on winner%** (53.9% vs 55.7%); we ship linear at inference unless product accepts ~1.8 pp winner hit for ~0.03 runs total MAE. Re-run `gametime-pregame-train` after member or split changes; holdout uses historical SP from `pitcher_games.parquet` (live Prob SP / distinct FIP is inference-only).

Both modes require the same `ensemble.json` artifact from `gametime-pregame-train`; the stacker block is always written at train time.

**13 members (production):** see roadmap [Current state](mlb_ensemble_roadmap.md#current-state-may-2026). **Research backlog:** [mlb_ensemble_research_backlog.md](mlb_ensemble_research_backlog.md).

## Total calibration (W9 — optional)

`pregame.calibration.total_enabled` (default **`false`**). When true, `pred_total` passes through `models/mlb/pregame/total_calibration.json` (val-fit). Re-run `gametime-pregame-train` after toggling.

## Local API (Predictions API v1)

Read-only HTTP service over the same ensemble as CLI (no train/download in request path).

```bash
pip install -e '.[api]'
uvicorn gametime.api.app:app --reload
# or: gametime-api
```

| Env | Default | Meaning |
|-----|---------|---------|
| `GAMETIME_ROOT` | repo root | Artifact and data root |
| `GAMETIME_CONFIG` | `configs/mlb.yaml` | MLB ensemble config |

```bash
curl -s http://127.0.0.1:8000/health | python3 -m json.tool
curl -s "http://127.0.0.1:8000/v1/slate?date=2024-06-15&regular_season=true"
curl -s "http://127.0.0.1:8000/v1/game?home=NYY&away=BOS&date=2024-06-15"
```

OpenAPI schema: `http://127.0.0.1:8000/openapi.json`. `GET /v1/game` returns **404** when the matchup is not on the slate for that date.

## Single game

```bash
gametime-pregame --config configs/mlb.yaml --home NYY --away BOS --regular-season
```

## Full slate (one date)

```bash
gametime-pregame-slate --config configs/mlb.yaml --date $(date +%Y-%m-%d) --regular-season
```

- `--date` defaults to today (local).
- Matchups come from `games.parquet` when that date has completed games; otherwise pybaseball team schedules (includes upcoming games).
- `--season YYYY` overrides season label for schedule fetch.
- `--decimals` (default **2**) controls printed `pred_total` / `pred_margin` precision in the slate table.
- Probable starters from the MLB schedule API (`hydrate=probablePitcher,team`) drive live pitcher features and the slate **Prob SP** column (away @ home last names). Each SP’s FIP is the latest **pre-game** value from `pitcher_games.parquet` for that pitcher ID, strictly before the slate date (not a synthetic cumulative rebuild). When probables are missing, team-level sidecar fallback is used and the column shows `—`.

## Retro slate backtest

Honest pregame accuracy over past calendar days: for each slate date, the predictor only sees games with `game_date < slate_date` (no same-day leakage). Outputs are separate from train holdout reports.

```bash
gametime-pregame-slate-backtest --config configs/mlb.yaml --days 14 --regular-season
```

| Flag | Default | Meaning |
|------|---------|---------|
| `--end-date` | Yesterday (or latest date in `games.parquet`) | Last day in the lookback window |
| `--days` | `14` | Window `(end_date - days, end_date]` with completed RS games |
| `--regular-season` | off | Score only `seasontype == rg` |
| `--append` | off | Concat new slate dates only if report files already exist |

Artifacts (under `reports/mlb/eval/` by default):

| File | Content |
|------|---------|
| `slate_backtest_daily.parquet` | Per `slate_date`: `n_games`, `total_mae`, `margin_mae`, `winner_accuracy`, `bias_total`, `blend_mode` |
| `slate_backtest_daily.json` | Same summary for quick diff |
| `slate_backtest_games.parquet` | Per-game preds vs actuals |

Truncated history snapshots: `data/mlb/processed/games_through_{YYYY-MM-DD}.parquet` (and matching `pitcher_games_through_{YYYY-MM-DD}.parquet` when the sidecar has orphan `game_id`s).

**Metrics (eval agent):** `total_mae` / `margin_mae` = mean absolute error on that slate; `winner_accuracy` = fraction with `pred_winner == actual_winner` (winner from margin sign); `bias_total` = mean signed `pred_total - actual_total`.

## Prediction log

Unless `--no-log`, predictions append to:

`data/live_predictions/pregame_predictions.parquet`

Columns include matchup, `pred_total`, `pred_margin`, `winner_tricode`, form counts, and timestamp.

## Troubleshooting

| Issue | Action |
|-------|--------|
| Stale form / Elo | Re-run `gametime-download`; extend `data.seasons` if the current year is missing |
| `No matchups found` | Off-day, All-Star break, or wrong `--date` / `--season` |
| `No train rows for member refit` | Check `train.train_seasons` in config |
| Team predict error | Team may lack history in `games.parquet` (expansion/rename); check tricode aliases in ingest |

See `docs/mlb_ensemble_roadmap.md` ([Current state](#current-state-may-2026), W7) for scope and ensemble roadmap.
