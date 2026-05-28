"""LightGBM ensemble member for MLB pregame total and margin."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import lightgbm as lgb
import pandas as pd

from gametime.pregame.baseball.features import (
    FEATURE_COLUMNS,
    TARGET_MARGIN,
    TARGET_TOTAL,
    TARGET_WINNER,
)
from gametime.pregame.baseball.models.base import BaseballMemberModel
from gametime.pregame.baseball.prediction import MemberPrediction
from gametime.train.common import lgb_binary_params, lgb_regression_params


def _train_booster(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    *,
    label: str,
    params: dict[str, Any],
    model_path: Path,
    num_boost_round: int = 500,
) -> lgb.Booster:
    dtrain = lgb.Dataset(train_df[FEATURE_COLUMNS], label=train_df[label])
    dval = lgb.Dataset(val_df[FEATURE_COLUMNS], label=val_df[label], reference=dtrain)
    booster = lgb.train(
        params,
        dtrain,
        num_boost_round=num_boost_round,
        valid_sets=[dval],
        callbacks=[lgb.early_stopping(50, verbose=False)],
    )
    booster.save_model(str(model_path))
    return booster


class LgbmMember(BaseballMemberModel):
    """Three LightGBM boosters: total runs, home margin, and direct home-win classifier."""

    name = "lgbm"

    def __init__(self, model_dir: Path) -> None:
        self._model_dir = model_dir
        self._boost_total: lgb.Booster | None = None
        self._boost_margin: lgb.Booster | None = None
        self._boost_winner: lgb.Booster | None = None

    def fit(self, train_df: pd.DataFrame, val_df: pd.DataFrame) -> None:
        self._model_dir.mkdir(parents=True, exist_ok=True)
        self._boost_total = _train_booster(
            train_df,
            val_df,
            label=TARGET_TOTAL,
            params=lgb_regression_params(num_leaves=31, min_data_in_leaf=30),
            model_path=self._model_dir / f"{TARGET_TOTAL}.txt",
        )
        self._boost_margin = _train_booster(
            train_df,
            val_df,
            label=TARGET_MARGIN,
            params=lgb_regression_params(num_leaves=31, min_data_in_leaf=30),
            model_path=self._model_dir / f"{TARGET_MARGIN}.txt",
        )
        self._boost_winner = _train_booster(
            train_df,
            val_df,
            label=TARGET_WINNER,
            params=lgb_binary_params(),
            model_path=self._model_dir / f"{TARGET_WINNER}.txt",
        )

    def predict(self, df: pd.DataFrame) -> MemberPrediction:
        if self._boost_total is None or self._boost_margin is None:
            raise RuntimeError("LgbmMember.predict called before fit")
        features = df[FEATURE_COLUMNS]
        return MemberPrediction(
            member=self.name,
            total=self._boost_total.predict(features),
            margin=self._boost_margin.predict(features),
        )

    def predict_winner_proba(self, df: pd.DataFrame) -> pd.Series:
        if self._boost_winner is None:
            raise RuntimeError("LgbmMember.predict_winner_proba called before fit")
        return pd.Series(
            self._boost_winner.predict(df[FEATURE_COLUMNS]),
            index=df.index,
        )
