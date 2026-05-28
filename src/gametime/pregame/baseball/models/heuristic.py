"""Simple baseline member for MLB pregame ensemble."""
from __future__ import annotations

import numpy as np
import pandas as pd

from gametime.pregame.baseball.models.base import BaseballMemberModel
from gametime.pregame.baseball.prediction import MemberPrediction


class HeuristicMember(BaseballMemberModel):
    """Uses rolling form features with train-time bias correction."""

    name = "heuristic"

    def __init__(self) -> None:
        self._margin_bias = 0.0
        self._total_bias = 0.0

    def fit(self, train_df: pd.DataFrame) -> None:
        raw_total = (
            train_df["home_form_runs_scored"].to_numpy() + train_df["away_form_runs_scored"].to_numpy()
        )
        raw_margin = (
            train_df["home_form_runs_scored"].to_numpy() - train_df["away_form_runs_scored"].to_numpy()
        )
        self._total_bias = float(train_df["total_final"].mean() - np.mean(raw_total))
        self._margin_bias = float(train_df["margin_final"].mean() - np.mean(raw_margin))

    def predict(self, df: pd.DataFrame) -> MemberPrediction:
        total = (
            df["home_form_runs_scored"].to_numpy()
            + df["away_form_runs_scored"].to_numpy()
            + self._total_bias
        )
        margin = (
            df["home_form_runs_scored"].to_numpy()
            - df["away_form_runs_scored"].to_numpy()
            + self._margin_bias
        )
        return MemberPrediction(member=self.name, total=total, margin=margin)
