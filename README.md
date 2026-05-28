# gametime

In-game NBA **total score** prediction. Playoff-focused live use; **train on regular season**, **test on playoffs**.

## Playoff vs regular season

| Split | Purpose |
|-------|---------|
| **Train (RS)** | 2021–2023 regular season — volume, stable pace |
| **Val (RS)** | 2024 regular season — early stopping / tuning |
| **Test (PO)** | 2024 playoffs — held-out eval (current slate) |

You should **not** train only on playoffs (too few games). You **should** report playoff MAE separately from RS.

## Commands

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

## Pre-game prediction

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

`configs/default.yaml` — adjust `train.test_season`, `train.test_seasontype: po`, and `data.seasons`.
