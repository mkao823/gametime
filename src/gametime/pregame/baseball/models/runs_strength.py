"""Runs-strength member: longer-window offensive/defensive rolling rates (no leakage)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from gametime.pregame.baseball.features import LEAGUE_RPG, _team_game_rows
from gametime.pregame.baseball.models.base import BaseballMemberModel
from gametime.pregame.baseball.prediction import MemberPrediction

STRENGTH_COLUMNS = [
    "home_rs_off",
    "home_rs_def",
    "away_rs_off",
    "away_rs_def",
]


def attach_runs_strength(
    table: pd.DataFrame,
    games: pd.DataFrame,
    *,
    window: int,
) -> pd.DataFrame:
    """Add per-game runs-strength columns using only prior games (shifted rolling)."""
    games = games.sort_values("game_date").reset_index(drop=True)
    tg = _team_game_rows(games)
    g = tg.groupby("team", sort=False)
    min_periods = max(3, window // 6)
    tg = tg.copy()
    tg["rs_off"] = g["runs_for"].transform(
        lambda s: s.shift(1).rolling(window, min_periods=min_periods).mean()
    )
    tg["rs_def"] = g["runs_against"].transform(
        lambda s: s.shift(1).rolling(window, min_periods=min_periods).mean()
    )

    home_ctx = tg[tg["is_home"] == 1].set_index("game_id")
    away_ctx = tg[tg["is_home"] == 0].set_index("game_id")

    out = table.copy()
    out["home_rs_off"] = out["game_id"].map(home_ctx["rs_off"])
    out["home_rs_def"] = out["game_id"].map(home_ctx["rs_def"])
    out["away_rs_off"] = out["game_id"].map(away_ctx["rs_off"])
    out["away_rs_def"] = out["game_id"].map(away_ctx["rs_def"])
    for col in STRENGTH_COLUMNS:
        out[col] = out[col].fillna(LEAGUE_RPG)
    return out


def _matchup_runs(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Expected home/away runs from offense vs opponent defense (league-neutral blend)."""
    home_runs = 0.5 * (df["home_rs_off"].to_numpy() + df["away_rs_def"].to_numpy())
    away_runs = 0.5 * (df["away_rs_off"].to_numpy() + df["home_rs_def"].to_numpy())
    return home_runs, away_runs


class RunsStrengthMember(BaseballMemberModel):
    """Matchup model from longer-window team runs scored/allowed rates."""

    name = "runs_strength"

    def __init__(self) -> None:
        self._total_bias = 0.0
        self._margin_bias = 0.0

    def fit(self, train_df: pd.DataFrame) -> None:
        home_runs, away_runs = _matchup_runs(train_df)
        raw_total = home_runs + away_runs
        raw_margin = home_runs - away_runs
        self._total_bias = float(train_df["total_final"].mean() - np.mean(raw_total))
        self._margin_bias = float(train_df["margin_final"].mean() - np.mean(raw_margin))

    def predict(self, df: pd.DataFrame) -> MemberPrediction:
        home_runs, away_runs = _matchup_runs(df)
        total = home_runs + away_runs + self._total_bias
        margin = home_runs - away_runs + self._margin_bias
        return MemberPrediction(member=self.name, total=total, margin=margin)
