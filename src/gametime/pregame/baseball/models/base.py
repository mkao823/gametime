"""Base protocol for MLB pregame ensemble member models."""
from __future__ import annotations

from typing import Protocol

import pandas as pd

from gametime.pregame.baseball.prediction import MemberPrediction


class BaseballMemberModel(Protocol):
    """Protocol shared by all baseball ensemble members."""

    name: str

    def fit(self, train_df: pd.DataFrame) -> None:
        """Learn member parameters from train data only."""

    def predict(self, df: pd.DataFrame) -> MemberPrediction:
        """Predict total and margin arrays for an evaluation split."""
