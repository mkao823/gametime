"""Pythagorean member: season-to-date RS/RA win% with implied runs (no leakage)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from gametime.pregame.baseball.features import LEAGUE_RPG, _team_game_rows
from gametime.pregame.baseball.models.base import BaseballMemberModel
from gametime.pregame.baseball.prediction import MemberPrediction

DEFAULT_PYTH_ALPHA = 1.83
ALPHA_GRID = (1.6, 1.7, 1.8, 1.83, 1.9, 2.0, 2.1, 2.2)
MARGIN_LOGIT_SCALE = 2.5

PYTH_COLUMNS = [
    "home_pyth_rs",
    "home_pyth_ra",
    "home_pyth_games",
    "away_pyth_rs",
    "away_pyth_ra",
    "away_pyth_games",
]


def _pyth_win_pct(rs: np.ndarray, ra: np.ndarray, alpha: float) -> np.ndarray:
    rs_a = np.maximum(rs, 0.1) ** alpha
    ra_a = np.maximum(ra, 0.1) ** alpha
    return rs_a / (rs_a + ra_a)


def _log5_home_win(home_wp: np.ndarray, away_wp: np.ndarray) -> np.ndarray:
    a = home_wp * (1.0 - away_wp)
    b = away_wp * (1.0 - home_wp)
    return a / np.maximum(a + b, 1e-9)


def _runs_per_game(cum_rs: np.ndarray, games: np.ndarray) -> np.ndarray:
    g = np.maximum(games, 1.0)
    return cum_rs / g


def attach_pythagorean(table: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """Season-to-date cumulative RS/RA per team (prior games only, reset each season)."""
    games = games.sort_values("game_date").reset_index(drop=True)
    tg = _team_game_rows(games)
    g = tg.groupby(["team", "season_start_year"], sort=False)
    tg = tg.copy()
    tg["pyth_rs"] = g["runs_for"].transform(lambda s: s.shift(1).expanding(min_periods=1).sum())
    tg["pyth_ra"] = g["runs_against"].transform(
        lambda s: s.shift(1).expanding(min_periods=1).sum()
    )
    tg["pyth_games"] = g["runs_for"].transform(
        lambda s: s.shift(1).expanding(min_periods=1).count()
    )

    home_ctx = tg[tg["is_home"] == 1].set_index("game_id")
    away_ctx = tg[tg["is_home"] == 0].set_index("game_id")

    out = table.copy()
    out["home_pyth_rs"] = out["game_id"].map(home_ctx["pyth_rs"])
    out["home_pyth_ra"] = out["game_id"].map(home_ctx["pyth_ra"])
    out["home_pyth_games"] = out["game_id"].map(home_ctx["pyth_games"])
    out["away_pyth_rs"] = out["game_id"].map(away_ctx["pyth_rs"])
    out["away_pyth_ra"] = out["game_id"].map(away_ctx["pyth_ra"])
    out["away_pyth_games"] = out["game_id"].map(away_ctx["pyth_games"])

    for rs_col, ra_col, games_col in (
        ("home_pyth_rs", "home_pyth_ra", "home_pyth_games"),
        ("away_pyth_rs", "away_pyth_ra", "away_pyth_games"),
    ):
        out[rs_col] = out[rs_col].fillna(LEAGUE_RPG)
        out[ra_col] = out[ra_col].fillna(LEAGUE_RPG)
        out[games_col] = out[games_col].fillna(0.0)
    return out


def _latest_pythagorean_rates(
    games: pd.DataFrame,
    *,
    home: str,
    away: str,
) -> dict[str, float]:
    """Season-to-date RS/RA totals from prior games only (for live inference)."""
    games = games.sort_values("game_date").reset_index(drop=True)
    tg = _team_game_rows(games)
    g = tg.groupby(["team", "season_start_year"], sort=False)
    tg = tg.copy()
    tg["pyth_rs"] = g["runs_for"].transform(lambda s: s.shift(1).expanding(min_periods=1).sum())
    tg["pyth_ra"] = g["runs_against"].transform(
        lambda s: s.shift(1).expanding(min_periods=1).sum()
    )
    tg["pyth_games"] = g["runs_for"].transform(
        lambda s: s.shift(1).expanding(min_periods=1).count()
    )

    def _last(team: str, col: str) -> float:
        sub = tg.loc[tg["team"] == team, col]
        if sub.empty or pd.isna(sub.iloc[-1]):
            return LEAGUE_RPG if col != "pyth_games" else 0.0
        return float(sub.iloc[-1])

    return {
        "home_pyth_rs": _last(home, "pyth_rs"),
        "home_pyth_ra": _last(home, "pyth_ra"),
        "home_pyth_games": _last(home, "pyth_games"),
        "away_pyth_rs": _last(away, "pyth_rs"),
        "away_pyth_ra": _last(away, "pyth_ra"),
        "away_pyth_games": _last(away, "pyth_games"),
    }


def _implied_runs(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Expected home/away runs from season RS/RA per-game rates."""
    home_rpg = _runs_per_game(
        df["home_pyth_rs"].to_numpy(), df["home_pyth_games"].to_numpy()
    )
    home_rapg = _runs_per_game(
        df["home_pyth_ra"].to_numpy(), df["home_pyth_games"].to_numpy()
    )
    away_rpg = _runs_per_game(
        df["away_pyth_rs"].to_numpy(), df["away_pyth_games"].to_numpy()
    )
    away_rapg = _runs_per_game(
        df["away_pyth_ra"].to_numpy(), df["away_pyth_games"].to_numpy()
    )
    home_runs = 0.5 * (home_rpg + away_rapg)
    away_runs = 0.5 * (away_rpg + home_rapg)
    return home_runs, away_runs


def _raw_predictions(df: pd.DataFrame, alpha: float) -> tuple[np.ndarray, np.ndarray]:
    home_wp = _pyth_win_pct(
        df["home_pyth_rs"].to_numpy(), df["home_pyth_ra"].to_numpy(), alpha
    )
    away_wp = _pyth_win_pct(
        df["away_pyth_rs"].to_numpy(), df["away_pyth_ra"].to_numpy(), alpha
    )
    p_home = _log5_home_win(home_wp, away_wp)
    p_home = np.clip(p_home, 1e-4, 1.0 - 1e-4)
    raw_margin = MARGIN_LOGIT_SCALE * np.log(p_home / (1.0 - p_home))
    home_runs, away_runs = _implied_runs(df)
    raw_total = home_runs + away_runs
    return raw_total, raw_margin


class PythagoreanMember(BaseballMemberModel):
    """Pythagorean win% from season RS/RA; margin from log5, total from implied runs."""

    name = "pythagorean"

    def __init__(self, *, default_alpha: float = DEFAULT_PYTH_ALPHA) -> None:
        self._alpha = default_alpha
        self._total_bias = 0.0
        self._margin_bias = 0.0

    def fit(self, train_df: pd.DataFrame) -> None:
        best_alpha = self._alpha
        best_mae = float("inf")
        actual_margin = train_df["margin_final"].to_numpy()
        for alpha in ALPHA_GRID:
            _, raw_margin = _raw_predictions(train_df, alpha)
            mae = float(np.mean(np.abs(raw_margin - actual_margin)))
            if mae < best_mae - 1e-9:
                best_mae = mae
                best_alpha = alpha
        self._alpha = best_alpha

        raw_total, raw_margin = _raw_predictions(train_df, self._alpha)
        self._total_bias = float(train_df["total_final"].mean() - np.mean(raw_total))
        self._margin_bias = float(train_df["margin_final"].mean() - np.mean(raw_margin))

    def predict(self, df: pd.DataFrame) -> MemberPrediction:
        raw_total, raw_margin = _raw_predictions(df, self._alpha)
        total = raw_total + self._total_bias
        margin = raw_margin + self._margin_bias
        return MemberPrediction(member=self.name, total=total, margin=margin)
