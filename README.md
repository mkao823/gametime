# gametime

Pregame and in-game sports prediction. This repo includes:

- **NBA** — in-game total score model + pregame (Elo/LGBM, optional Vegas blend)
- **MLB** — pregame **ensemble** for game total runs and winner (no live in-game model yet)

---

## MLB pregame ensemble

MLB pregame predicts **total runs** and **home margin** (winner from margin sign) using multiple independent **members**, then blends them. Training uses regular-season history; weights and the stacker are fit on **val 2024** only; **test 2025** is a held-out report.

### Approach

1. **Members** — Each member outputs `pred_total` and `pred_margin` per game (heuristics, generative models, ingest-backed context, etc.).
2. **Linear blend** — Grid-searched weights on validation (`min_member_weight` / `max_member_weight` in config).
3. **Ridge stacking (production)** — With `use_stacking: true`, final preds are a ridge meta-model on member outputs (coefficients fit on val, frozen for test/inference). Slate backtest and `gametime-pregame` use stacking when enabled.
4. **No leakage** — Features and sidecars use only information available before first pitch; retro slate backtest uses `game_date < slate_date`.

### Current members (12)

| Member | Signal |
|--------|--------|
| `lgbm` | Gradient boosting on rolling form + context columns |
| `heuristic` | Short-window team form |
| `runs_strength` | 30-game offensive/defensive strength |
| `poisson` | Poisson / run-rate generative totals |
| `pythagorean` | Pythagorean expectation → implied runs |
| `pitcher` | Starting pitcher quality (M1 sidecar) |
| `park_factor` | Home park run environment |
| `weather` | Game-time weather (Open-Meteo sidecar) |
| `travel_rest` | Schedule fatigue (rest, games in 3d, road streak) |
| `series_context` | Same-opponent series game index + prior-game style |
| `elo` | Baseball Elo ratings |
| `h2h` | Shrunk head-to-head history |

**Backlog (roadmap):** `lineup` (W6k), optional `market` / Vegas (deferred). See [docs/mlb_ensemble_roadmap.md](docs/mlb_ensemble_roadmap.md).

### Feature roadmap (ingest → `has_*` flags)

| Milestone | Unlocks | Status |
|-----------|---------|--------|
| M1 Starting pitcher | `pitcher` | Shipped |
| M2 Park factors | `park_factor` | Shipped |
| M3 Weather | `weather` | Shipped |
| M4 Lineups | `lineup` | W6k (in progress) |
| M5 Historical odds | `market` member | Deferred (no `ODDS_API_KEY`) |

Placeholder columns in `FEATURE_COLUMNS` (`has_lineup`, etc.) flip to `1` when ingest populates real data.

### MLB commands

```bash
pip install -e '.[mlb]'

gametime-download --config configs/mlb.yaml
gametime-pregame-train --config configs/mlb.yaml
# → models/mlb/pregame/ensemble.json, reports/mlb/eval/pregame_summary.json

gametime-pregame --config configs/mlb.yaml --home NYY --away BOS --regular-season
gametime-pregame-slate --config configs/mlb.yaml --date $(date +%Y-%m-%d) --regular-season

# Honest retro eval (no same-day leakage)
gametime-pregame-slate-backtest --config configs/mlb.yaml --days 14 --regular-season
```

**Docs:** [docs/mlb_pregame_ops.md](docs/mlb_pregame_ops.md) (ops + slate backtest), [docs/mlb_ensemble_roadmap.md](docs/mlb_ensemble_roadmap.md) (phases, worker windows, iteration SOP).

**Config:** `configs/mlb.yaml` — seasons, `pregame.ensemble.members`, `use_stacking`, val/test splits.

---

## NBA — playoff vs regular season

| Split | Purpose |
|-------|---------|
| **Train (RS)** | 2021–2023 regular season — volume, stable pace |
| **Val (RS)** | 2024 regular season — early stopping / tuning |
| **Test (PO)** | 2024 playoffs — held-out eval (current slate) |

## NBA commands

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# Data: regular + playoff PBP (seasontype: both in config)
gametime-download
gametime-build
gametime-train

# Held-out playoff test + by-phase / by-season tables
gametime-eval
# → reports/eval/summary.json, mae_by_phase.csv, mae_by_season.csv

# Peak/trough signal backtest on playoff test set
gametime-backtest-signals
# → reports/signals/summary.json

# Live (auto-dated JSON: reports/live/live_20260525_NYK_CLE.json)
gametime-live --away NYK --home CLE --interval 30

# Include Kalshi implied O/U + spread (public API, no key)
gametime-live --away SAS --home OKC --interval 30 --kalshi

# Or custom name (date added if omitted): reports/live_nyk_cle.json -> live_20260525_nyk_cle.json
gametime-live --away NYK --home CLE --json-out reports/live_nyk_cle.json

# All logged games — aggregate phase MAE
gametime-analyze-live

# Single game — tier breakdown, pace story, timeline CSV
gametime-analyze-game --away OKC --home SAS
# → reports/live_analysis/0042500314_timeline.csv
# → reports/live_analysis/0042500314_summary.json
```

## NBA pre-game prediction

Two CLIs sit alongside the in-game model: a **pure** team-features model (Elo +
last-10 form, no betting data) and a **Vegas-blended** variant that combines the
pure model with the live spread/total.

```bash
# One-time: build team_games.parquet, fit Elo, train LightGBM total + margin
gametime-pregame-train
# → models/pregame/{total_final,margin_final}.txt, elo_state.json, meta.json
# → reports/eval/pregame_summary.json (val + playoff test MAE, winner accuracy)

# Pure model (no Vegas)
gametime-pregame --away SAS --home OKC

# Vegas-blended (needs ODDS_API_KEY from https://the-odds-api.com/)
export ODDS_API_KEY=...
gametime-pregame --away SAS --home OKC --with-vegas

# Manual override (skip the API; supply your own line)
gametime-pregame --away SAS --home OKC --spread -4.5 --total 215.5

# Tune blend weight (0 = model only, 1 = market only; default 0.5)
gametime-pregame --away SAS --home OKC --with-vegas --vegas-weight 0.7
```

Pre-game predictions are logged to
`data/live_predictions/pregame_predictions.parquet` so they can be compared
against the eventual actual final score after the game.

Add `--regular-season` if the matchup is not a playoff game (default treats it
as playoff so the `is_playoff` feature is on).

## Config

| Sport | Config |
|-------|--------|
| NBA | `configs/default.yaml` — `train.test_season`, `train.test_seasontype: po`, `data.seasons` |
| MLB | `configs/mlb.yaml` — ensemble members, val/test seasons, ingest paths |
