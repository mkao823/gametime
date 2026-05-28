"""Shared training utilities (splits, LightGBM defaults) across sport pipelines."""
from __future__ import annotations

from typing import Any

import pandas as pd

from gametime.data.game_meta import filter_games


def lgb_regression_params(**overrides: Any) -> dict[str, Any]:
    params = {
        "objective": "regression",
        "metric": "mae",
        "verbosity": -1,
        "learning_rate": 0.05,
        "num_leaves": 63,
        "min_data_in_leaf": 200,
        "feature_fraction": 0.9,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
    }
    params.update(overrides)
    return params


def lgb_binary_params(**overrides: Any) -> dict[str, Any]:
    params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "verbosity": -1,
        "learning_rate": 0.05,
        "num_leaves": 31,
        "min_data_in_leaf": 20,
        "feature_fraction": 0.9,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
    }
    params.update(overrides)
    return params


def split_snapshots_by_config(df: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """In-game snapshot train / val / test from config."""
    train_cfg = cfg.get("train", {})
    train = filter_games(
        df,
        seasons=train_cfg.get("train_seasons"),
        seasontypes=train_cfg.get("train_seasontypes", ["rg"]),
    )
    val = filter_games(
        df,
        seasons=[train_cfg["val_season"]] if train_cfg.get("val_season") else None,
        seasontypes=[train_cfg.get("val_seasontype", "rg")],
    )
    test_seasons = train_cfg.get("test_seasons") or (
        [train_cfg["test_season"]] if train_cfg.get("test_season") else None
    )
    test = filter_games(
        df,
        seasons=test_seasons,
        seasontypes=[train_cfg.get("test_seasontype", "po")],
    )
    return train, val, test


def split_table_by_season(
    table: pd.DataFrame,
    *,
    train_seasons: list[int],
    train_seasontypes: list[str],
    val_season: int,
    val_seasontype: str,
    test_seasons: list[int],
    test_seasontype: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """One row per game pregame tables."""
    train = table[
        table["season_start_year"].isin(train_seasons) & table["seasontype"].isin(train_seasontypes)
    ]
    val = table[
        (table["season_start_year"] == val_season) & (table["seasontype"] == val_seasontype)
    ]
    test = table[
        table["season_start_year"].isin(test_seasons) & (table["seasontype"] == test_seasontype)
    ]
    return train, val, test
