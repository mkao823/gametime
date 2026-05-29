"""Park run-environment factors for MLB pregame (M2 / W6i).

Method (v1):
  - ``park_factors.parquet``: stable multiplicative factor per home team —
    mean ``total_final`` at that home venue / league mean ``total_final``.
  - Per-game factors use **shifted** expanding means (only games strictly before
    the current game) so in-season updates do not leak outcomes.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

PARK_FACTOR_COLUMNS = ["home_team", "park_factor_runs", "park_factor_hr"]
LEAGUE_PARK_FACTOR = 1.0
DEFAULT_MIN_HOME_GAMES_STATIC = 30
DEFAULT_MIN_HOME_GAMES_SHIFTED = 15
DEFAULT_MIN_LEAGUE_GAMES = 50


def _ensure_total_final(games: pd.DataFrame) -> pd.Series:
    if "total_final" in games.columns:
        return games["total_final"].astype(float)
    return games["home_runs"].astype(float) + games["away_runs"].astype(float)


def build_static_park_factors(
    games: pd.DataFrame,
    *,
    min_home_games: int = DEFAULT_MIN_HOME_GAMES_STATIC,
) -> pd.DataFrame:
    if games.empty:
        return pd.DataFrame(columns=PARK_FACTOR_COLUMNS)
    games = games.sort_values("game_date").reset_index(drop=True)
    total = _ensure_total_final(games)
    league_mean = float(total.mean()) or 9.0
    rows: list[dict[str, float | str]] = []
    for team, sub in games.assign(total_final=total).groupby("home_team", sort=False):
        if len(sub) < min_home_games:
            continue
        rows.append(
            {
                "home_team": str(team),
                "park_factor_runs": float(sub["total_final"].mean() / league_mean),
                "park_factor_hr": np.nan,
            }
        )
    return (
        pd.DataFrame(rows).sort_values("home_team").reset_index(drop=True)
        if rows
        else pd.DataFrame(columns=PARK_FACTOR_COLUMNS)
    )


def build_shifted_park_factors(games: pd.DataFrame) -> pd.DataFrame:
    if games.empty:
        return pd.DataFrame(
            columns=["game_id", "home_park_factor", "park_factor_log", "has_park_factor"]
        )
    games = games.sort_values("game_date").reset_index(drop=True)
    total = _ensure_total_final(games)
    g = games[["game_id", "home_team"]].copy()
    g["total_final"] = total
    g["league_prior_mean"] = g["total_final"].shift(1).expanding(
        min_periods=DEFAULT_MIN_LEAGUE_GAMES
    ).mean()
    home_prior = g.groupby("home_team", sort=False)["total_final"].transform(
        lambda s: s.shift(1).expanding(min_periods=DEFAULT_MIN_HOME_GAMES_SHIFTED).mean()
    )
    home_n = g.groupby("home_team", sort=False).cumcount()
    pf = (home_prior / g["league_prior_mean"].replace(0, np.nan)).fillna(LEAGUE_PARK_FACTOR)
    has = (
        (home_n >= DEFAULT_MIN_HOME_GAMES_SHIFTED)
        & home_prior.notna()
        & g["league_prior_mean"].notna()
    ).astype(int)
    return pd.DataFrame(
        {
            "game_id": g["game_id"],
            "home_park_factor": pf,
            "park_factor_log": np.log(pf.clip(lower=0.5, upper=2.0)),
            "has_park_factor": has,
        }
    )


def download_park_factors(
    games_path: Path,
    out_path: Path,
    *,
    min_home_games: int = DEFAULT_MIN_HOME_GAMES_STATIC,
) -> Path:
    games = pd.read_parquet(games_path)
    table = build_static_park_factors(games, min_home_games=min_home_games)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(out_path, index=False)
    print(f"[mlb-park] Wrote {len(table)} teams → {out_path}")
    return out_path


def load_park_factors(path: Path | None) -> pd.DataFrame:
    if path is None or not Path(path).exists():
        return pd.DataFrame(columns=PARK_FACTOR_COLUMNS)
    df = pd.read_parquet(path)
    for col in PARK_FACTOR_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
    return df
