"""Train MLB pregame total runs + home margin (winner from margin sign)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from gametime.pregame.baseball.features import (
    FEATURE_COLUMNS,
    TARGET_MARGIN,
    TARGET_TOTAL,
    TARGET_WINNER,
    build_training_table,
)
from gametime.train.common import lgb_binary_params, lgb_regression_params, split_table_by_season


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


def _metrics(pred_total: np.ndarray, pred_margin: np.ndarray, df: pd.DataFrame) -> dict[str, float]:
    if len(df) == 0:
        return {}
    actual_total = df[TARGET_TOTAL].to_numpy()
    actual_margin = df[TARGET_MARGIN].to_numpy()
    pred_winner = pred_margin > 0
    actual_winner = actual_margin > 0
    return {
        "n": float(len(df)),
        "total_mae": float(np.mean(np.abs(pred_total - actual_total))),
        "margin_mae": float(np.mean(np.abs(pred_margin - actual_margin))),
        "winner_accuracy": float(np.mean(pred_winner == actual_winner)),
    }


def train_baseball_pregame(
    *,
    games_path: Path,
    model_dir: Path,
    report_path: Path,
    train_seasons: list[int],
    train_seasontypes: list[str],
    val_season: int,
    val_seasontype: str,
    test_seasons: list[int],
    test_seasontype: str,
    form_window: int = 10,
) -> dict[str, Any]:
    games = pd.read_parquet(games_path)
    table = build_training_table(games, form_window=form_window)
    train_df, val_df, test_df = split_table_by_season(
        table,
        train_seasons=train_seasons,
        train_seasontypes=train_seasontypes,
        val_season=val_season,
        val_seasontype=val_seasontype,
        test_seasons=test_seasons,
        test_seasontype=test_seasontype,
    )
    if len(val_df) == 0:
        fallback = max(train_seasons)
        val_df = table[
            (table["season_start_year"] == fallback)
            & (table["seasontype"] == val_seasontype)
        ]
        print(f"[mlb-pregame] val empty; using season {fallback}")

    model_dir.mkdir(parents=True, exist_ok=True)
    print(f"[mlb-pregame] train={len(train_df)} val={len(val_df)} test={len(test_df)}")

    total_model = model_dir / f"{TARGET_TOTAL}.txt"
    margin_model = model_dir / f"{TARGET_MARGIN}.txt"
    winner_model = model_dir / f"{TARGET_WINNER}.txt"

    boost_total = _train_booster(
        train_df,
        val_df,
        label=TARGET_TOTAL,
        params=lgb_regression_params(num_leaves=31, min_data_in_leaf=30),
        model_path=total_model,
    )
    boost_margin = _train_booster(
        train_df,
        val_df,
        label=TARGET_MARGIN,
        params=lgb_regression_params(num_leaves=31, min_data_in_leaf=30),
        model_path=margin_model,
    )
    boost_winner = _train_booster(
        train_df,
        val_df,
        label=TARGET_WINNER,
        params=lgb_binary_params(),
        model_path=winner_model,
    )

    pred_total_val = boost_total.predict(val_df[FEATURE_COLUMNS])
    pred_margin_val = boost_margin.predict(val_df[FEATURE_COLUMNS])
    pred_total_test = boost_total.predict(test_df[FEATURE_COLUMNS])
    pred_margin_test = boost_margin.predict(test_df[FEATURE_COLUMNS])

    meta = {
        "sport": "mlb",
        "form_window": form_window,
        "feature_columns": FEATURE_COLUMNS,
        "train_n": len(train_df),
        "val_n": len(val_df),
        "test_n": len(test_df),
        "val": _metrics(pred_total_val, pred_margin_val, val_df),
        "test": _metrics(pred_total_test, pred_margin_test, test_df),
        "winner_val_acc_direct": float(
            np.mean((boost_winner.predict(val_df[FEATURE_COLUMNS]) >= 0.5) == val_df[TARGET_WINNER])
        )
        if len(val_df)
        else None,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w") as f:
        json.dump(meta, f, indent=2)
    with (model_dir / "meta.json").open("w") as f:
        json.dump(meta, f, indent=2)
    print(f"[mlb-pregame] Wrote {report_path}")
    return meta
