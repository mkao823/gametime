# MLB pregame operations

Production workflow for the six-member MLB pregame ensemble (`lgbm`, `heuristic`, `runs_strength`, `poisson`, `pythagorean`, `elo`). No `ODDS_API_KEY` required.

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

```bash
gametime-download --config configs/mlb.yaml
```

Confirm processed games include yesterday:

```bash
python3 -c "
import pandas as pd
g = pd.read_parquet('data/mlb/processed/games.parquet')
g['game_date'] = pd.to_datetime(g['game_date'])
print('rows', len(g), 'max_date', g['game_date'].max().date())
"
```

## Train artifacts

Run when `models/mlb/pregame/ensemble.json` is missing or after member/weight changes:

```bash
gametime-pregame-train --config configs/mlb.yaml
```

Artifacts: `models/mlb/pregame/ensemble.json`, `meta.json`, `lgbm_*.txt`, eval under `reports/mlb/eval/`.

Member list in config must match `pregame.ensemble.members` (six members above).

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

See `docs/mlb_ensemble_roadmap.md` (W7) for scope and ensemble roadmap.
