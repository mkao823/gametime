"""Train MLB pregame total runs + home margin (winner from margin sign)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from gametime.pregame.baseball.ensemble import (
    combine,
    combine_equal,
    fit_weights_with_metrics,
)
from gametime.pregame.baseball.features import (
    FEATURE_COLUMNS,
    TARGET_MARGIN,
    TARGET_TOTAL,
    TARGET_WINNER,
    build_training_table,
)
from gametime.pregame.baseball.models.heuristic import HeuristicMember
from gametime.pregame.baseball.models.lgbm import LgbmMember
from gametime.pregame.baseball.models.runs_strength import (
    RunsStrengthMember,
    attach_runs_strength,
)
from gametime.pregame.baseball.prediction import MemberPrediction
from gametime.train.common import split_table_by_season


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
    runs_strength_window: int = 30,
    tune_ensemble_weights: bool = True,
    weight_grid_step: float = 0.1,
) -> dict[str, Any]:
    games = pd.read_parquet(games_path)
    table = build_training_table(games, form_window=form_window)
    table = attach_runs_strength(table, games, window=runs_strength_window)
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

    lgbm = LgbmMember(model_dir)
    lgbm.fit(train_df, val_df)
    heuristic = HeuristicMember()
    heuristic.fit(train_df)
    runs_strength = RunsStrengthMember()
    runs_strength.fit(train_df)

    members: list[LgbmMember | HeuristicMember | RunsStrengthMember] = [
        lgbm,
        heuristic,
        runs_strength,
    ]
    val_preds: dict[str, MemberPrediction] = {}
    test_preds: dict[str, MemberPrediction] = {}
    for member in members:
        val_preds[member.name] = member.predict(val_df)
        test_preds[member.name] = member.predict(test_df)

    member_pred_list = list(val_preds.values())
    ensemble_equal_val = combine_equal(member_pred_list)
    ensemble_equal_test = combine_equal(list(test_preds.values()))

    actual_total_val = val_df[TARGET_TOTAL].to_numpy()
    actual_margin_val = val_df[TARGET_MARGIN].to_numpy()
    weights_total: dict[str, float] = {}
    weights_margin: dict[str, float] = {}
    val_tune_metrics: dict[str, float] = {}
    if tune_ensemble_weights:
        weights_total, weights_margin, val_tune_metrics = fit_weights_with_metrics(
            member_pred_list,
            actual_total_val,
            actual_margin_val,
            step=weight_grid_step,
        )
        ensemble_weighted_val = combine(
            member_pred_list,
            weights_total=weights_total,
            weights_margin=weights_margin,
        )
        ensemble_weighted_test = combine(
            list(test_preds.values()),
            weights_total=weights_total,
            weights_margin=weights_margin,
        )
    else:
        ensemble_weighted_val = ensemble_equal_val
        ensemble_weighted_test = ensemble_equal_test

    member_names = [member.name for member in members]
    ensemble_payload = {
        "version": 1,
        "members": member_names,
        "weights": {"total": weights_total, "margin": weights_margin},
        "winner_mode": "sign_margin",
        "val_metrics": val_tune_metrics,
    }
    with (model_dir / "ensemble.json").open("w") as f:
        json.dump(ensemble_payload, f, indent=2)

    lgbm_val = val_preds["lgbm"]
    lgbm_test = test_preds["lgbm"]

    meta = {
        "sport": "mlb",
        "form_window": form_window,
        "runs_strength_window": runs_strength_window,
        "feature_columns": FEATURE_COLUMNS,
        "train_n": len(train_df),
        "val_n": len(val_df),
        "test_n": len(test_df),
        "val": _metrics(lgbm_val.total, lgbm_val.margin, val_df),
        "test": _metrics(lgbm_test.total, lgbm_test.margin, test_df),
        "members": {
            name: {
                "val": _metrics(val_preds[name].total, val_preds[name].margin, val_df),
                "test": _metrics(test_preds[name].total, test_preds[name].margin, test_df),
            }
            for name in val_preds
        },
        "ensemble_equal": {
            "val": _metrics(ensemble_equal_val.total, ensemble_equal_val.margin, val_df),
            "test": _metrics(ensemble_equal_test.total, ensemble_equal_test.margin, test_df),
        },
        "ensemble": {
            "weights": {"total": weights_total, "margin": weights_margin},
            "val": _metrics(
                ensemble_weighted_val.total, ensemble_weighted_val.margin, val_df
            ),
            "test": _metrics(
                ensemble_weighted_test.total, ensemble_weighted_test.margin, test_df
            ),
        },
        "winner_val_acc_direct": float(
            np.mean((lgbm.predict_winner_proba(val_df) >= 0.5) == val_df[TARGET_WINNER])
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
