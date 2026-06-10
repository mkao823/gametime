---
title: Methodology
description: How our MLB pregame ensemble predicts total runs and winners, what data we use, and how we evaluate accuracy.
---

# Methodology

This page explains how our MLB pregame predictions are produced. The goal is transparency: what the model does, what data it uses, and what it does **not** guarantee.

## What we predict

For each scheduled regular-season game **before first pitch**, we estimate:

- **Total runs** — combined runs scored by both teams
- **Home margin** — home team runs minus away team runs
- **Winner** — the team with positive predicted margin (home or away)

Predictions are **pregame only**. We do not update them during live play, and we do not model in-game situations.

## Ensemble approach

Rather than relying on a single formula, we run **13 independent members**. Each member outputs its own `pred_total` and `pred_margin` for every game. Members use different signals — gradient boosting, generative run models, schedule context, park and weather sidecars, and more.

At inference, member outputs are combined with a **linear weighted blend**. Blend weights are grid-searched on a validation season and frozen before any held-out test evaluation. Production uses linear blending (`use_stacking: false`); we do not apply a stacked meta-learner at inference.

| Member | Signal |
|--------|--------|
| `lgbm` | Gradient boosting on rolling form and context columns |
| `heuristic` | Short-window team form |
| `runs_strength` | 30-game offensive and defensive strength |
| `poisson` | Poisson / run-rate generative totals |
| `pythagorean` | Pythagorean expectation → implied runs |
| `pitcher` | Starting pitcher quality (pitcher sidecar) |
| `park_factor` | Home park run environment |
| `weather` | Game-time weather (Open-Meteo sidecar) |
| `lineup` | Lineup wOBA and platoon (lineup sidecar) |
| `travel_rest` | Schedule fatigue — rest days, games in three days, road streak |
| `series_context` | Same-opponent series game index and prior-game style |
| `elo` | Baseball Elo ratings |
| `h2h` | Shrunk head-to-head history |

New members must pass a **decorrelation gate**: on the test holdout, each member’s total-run errors should not be too highly correlated with every existing member (Pearson *r* &lt; 0.94 vs all incumbents). This keeps the ensemble from stacking redundant copies of the same signal.

## Data sources

Game history and features are built from public sources:

| Layer | Source | Role |
|-------|--------|------|
| Bulk game logs | [pybaseball](https://github.com/jldbc/pybaseball) (`schedule_and_record`) | Season rebuild of completed games with runs scored |
| Recent gap-fill | [MLB Stats API](https://statsapi.mlb.com/) | Append **Final** games when Baseball Reference lags by a few days |
| Starting pitchers | MLB Stats API boxscores | Pitcher game logs and probable-starter features |
| Park factors | Derived from historical home/away scoring | Run environment by venue |
| Weather | [Open-Meteo](https://open-meteo.com/) | Game-time conditions at the ballpark |
| Lineups | MLB Stats API boxscores | Batting order and cumulative wOBA when parseable |

Processed tables live as Parquet sidecars (games, pitchers, park, weather, lineups) alongside the main `games.parquet` log. The download pipeline refreshes data on a daily cadence before slate predictions are generated.

## No leakage

Features use only information that would have been available **before game time**:

- Rolling form, Elo, and head-to-head stats use games with `game_date` strictly before the slate date.
- Probable starters and weather are resolved as-of pregame, not from postgame boxscores.
- Retro evaluation (`slate backtest`) replays each historical slate with `game_date < slate_date` so same-day results never leak into that day’s predictions.

When lineup or pitcher boxscores cannot be parsed, we mark coverage flags (`has_lineup`, `has_starting_pitcher`) accordingly — we do not invent confirmed lineups.

## Holdout discipline

Training and evaluation follow fixed season splits:

| Split | Seasons | Purpose |
|-------|---------|---------|
| Train | 2021–2023 regular season | Fit member models and base features |
| Validation | 2024 regular season | Tune ensemble blend weights only |
| Test | 2025 regular season | **Report-only** holdout — never used for tuning |

Weights are refit on validation whenever members or features change. Test-season metrics are published for honesty checks but do not feed back into model selection.

## Reported accuracy

On the **2025 regular-season test holdout** (post starting-pitcher and lineup backfill), the linear ensemble achieved:

| Metric | Value |
|--------|-------|
| Total runs MAE | **3.615** |
| Winner accuracy | **55.3%** |

Mean absolute error (MAE) measures how far predicted totals are from actual totals on average. Winner accuracy is the share of games where the predicted winner (from margin sign) matched the actual winner.

**Past performance does not guarantee future results.** MLB rosters, rules, and run environments change; holdout metrics describe one historical window, not a promise of edge against betting markets or future seasons.

We do **not** report ROI, units won, or “beat the market” claims unless and until a validated market-comparison feature ships.

## What we don’t model

- **In-game / live play** — no pitch-by-pitch or inning-by-inning updates
- **Official betting lines** — closing totals and spreads are not ensemble members today (a market feature is deferred pending a reliable odds source)
- **Breaking injury news** — unless reflected in published probable starters or sidecars at download time
- **Guaranteed outcomes** — all outputs are probabilistic estimates with real error

## Updates

- **Data** — `gametime-download` refreshes game logs and sidecars; slates should run only when processed games include through yesterday.
- **Models** — `gametime-pregame-train` reruns when members, weights, or train/val/test splits change; artifacts are versioned under `models/mlb/pregame/`.
- **This page** — updated when methodology, member list, or published holdout metrics change.
