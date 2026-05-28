"""Poisson member: team attack/def rates from shifted cumulative RS/RA (no leakage)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from gametime.pregame.baseball.features import LEAGUE_RPG, _team_game_rows
from gametime.pregame.baseball.models.base import BaseballMemberModel
from gametime.pregame.baseball.prediction import MemberPrediction

POISSON_COLUMNS = [
    "home_poisson_attack",
    "home_poisson_defense",
    "away_poisson_attack",
    "away_poisson_defense",
]


def attach_poisson(table: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """Add per-game Poisson rate columns using only prior games (shifted expanding mean)."""
    games = games.sort_values("game_date").reset_index(drop=True)
    tg = _team_game_rows(games)
    g = tg.groupby("team", sort=False)
    tg = tg.copy()
    tg["poisson_attack"] = g["runs_for"].transform(
        lambda s: s.shift(1).expanding(min_periods=1).mean()
    )
    tg["poisson_defense"] = g["runs_against"].transform(
        lambda s: s.shift(1).expanding(min_periods=1).mean()
    )

    home_ctx = tg[tg["is_home"] == 1].set_index("game_id")
    away_ctx = tg[tg["is_home"] == 0].set_index("game_id")

    out = table.copy()
    out["home_poisson_attack"] = out["game_id"].map(home_ctx["poisson_attack"])
    out["home_poisson_defense"] = out["game_id"].map(home_ctx["poisson_defense"])
    out["away_poisson_attack"] = out["game_id"].map(away_ctx["poisson_attack"])
    out["away_poisson_defense"] = out["game_id"].map(away_ctx["poisson_defense"])
    for col in POISSON_COLUMNS:
        out[col] = out[col].fillna(LEAGUE_RPG)
    return out


def _latest_poisson_rates(
    games: pd.DataFrame,
    *,
    home: str,
    away: str,
) -> dict[str, float]:
    """Per-team attack/def rates from prior games only (for live inference)."""
    games = games.sort_values("game_date").reset_index(drop=True)
    tg = _team_game_rows(games)
    g = tg.groupby("team", sort=False)
    tg = tg.copy()
    tg["poisson_attack"] = g["runs_for"].transform(
        lambda s: s.shift(1).expanding(min_periods=1).mean()
    )
    tg["poisson_defense"] = g["runs_against"].transform(
        lambda s: s.shift(1).expanding(min_periods=1).mean()
    )

    def _last(team: str, col: str) -> float:
        sub = tg.loc[tg["team"] == team, col]
        if sub.empty or pd.isna(sub.iloc[-1]):
            return LEAGUE_RPG
        return float(sub.iloc[-1])

    return {
        "home_poisson_attack": _last(home, "poisson_attack"),
        "home_poisson_defense": _last(home, "poisson_defense"),
        "away_poisson_attack": _last(away, "poisson_attack"),
        "away_poisson_defense": _last(away, "poisson_defense"),
    }


def _matchup_lambdas(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Expected home/away scoring rates (geometric blend of attack vs opponent defense)."""
    lam_home = np.sqrt(
        df["home_poisson_attack"].to_numpy() * df["away_poisson_defense"].to_numpy()
    )
    lam_away = np.sqrt(
        df["away_poisson_attack"].to_numpy() * df["home_poisson_defense"].to_numpy()
    )
    return lam_home, lam_away


class PoissonMember(BaseballMemberModel):
    """Generative total/margin from cumulative team attack and defense rates."""

    name = "poisson"

    def __init__(self) -> None:
        self._total_bias = 0.0
        self._margin_bias = 0.0

    def fit(self, train_df: pd.DataFrame) -> None:
        lam_home, lam_away = _matchup_lambdas(train_df)
        raw_total = lam_home + lam_away
        raw_margin = lam_home - lam_away
        self._total_bias = float(train_df["total_final"].mean() - np.mean(raw_total))
        self._margin_bias = float(train_df["margin_final"].mean() - np.mean(raw_margin))

    def predict(self, df: pd.DataFrame) -> MemberPrediction:
        lam_home, lam_away = _matchup_lambdas(df)
        total = lam_home + lam_away + self._total_bias
        margin = lam_home - lam_away + self._margin_bias
        return MemberPrediction(member=self.name, total=total, margin=margin)
