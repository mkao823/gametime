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
    stack_fit_with_metrics,
    stack_predict,
)
from gametime.pregame.baseball.features import (
    FEATURE_COLUMNS,
    TARGET_MARGIN,
    TARGET_TOTAL,
    TARGET_WINNER,
    build_training_table,
)
from gametime.pregame.baseball.models.elo import (
    BaseballEloParams,
    EloMember,
    attach_elo,
    fit_baseball_elo,
    save_member_state,
)
from gametime.pregame.baseball.models.heuristic import HeuristicMember
from gametime.pregame.baseball.models.lgbm import LgbmMember
from gametime.pregame.baseball.models.poisson import PoissonMember, attach_poisson
from gametime.pregame.baseball.models.pythagorean import (
    PythagoreanMember,
    attach_pythagorean,
)
from gametime.pregame.baseball.models.runs_strength import (
    RunsStrengthMember,
    attach_runs_strength,
)
from gametime.pregame.baseball.prediction import (
    EnsemblePrediction,
    MemberPrediction,
)
from gametime.train.common import split_table_by_season


def _build_predictions_export_frame(
    df: pd.DataFrame,
    member_preds: dict[str, MemberPrediction],
    ensemble_equal: EnsemblePrediction,
    ensemble_weighted: EnsemblePrediction,
    ensemble_stacked: EnsemblePrediction | None = None,
) -> pd.DataFrame:
    """One row per game with actuals, member preds, and ensemble outputs."""
    out = pd.DataFrame(
        {
            "game_id": df["game_id"].values,
            "season_start_year": df["season_start_year"].values,
            "actual_total": df[TARGET_TOTAL].to_numpy(),
            "actual_margin": df[TARGET_MARGIN].to_numpy(),
        }
    )
    for name, pred in member_preds.items():
        out[f"{name}_total"] = pred.total
        out[f"{name}_margin"] = pred.margin
    out["ensemble_equal_total"] = ensemble_equal.total
    out["ensemble_equal_margin"] = ensemble_equal.margin
    out["ensemble_total"] = ensemble_weighted.total
    out["ensemble_margin"] = ensemble_weighted.margin
    if ensemble_stacked is not None:
        out["ensemble_stacked_total"] = ensemble_stacked.total
        out["ensemble_stacked_margin"] = ensemble_stacked.margin
    return out


def export_split_predictions(
    *,
    df: pd.DataFrame,
    member_preds: dict[str, MemberPrediction],
    ensemble_equal: EnsemblePrediction,
    ensemble_weighted: EnsemblePrediction,
    path: Path,
    ensemble_stacked: EnsemblePrediction | None = None,
) -> None:
    frame = _build_predictions_export_frame(
        df,
        member_preds,
        ensemble_equal,
        ensemble_weighted,
        ensemble_stacked,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


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
    min_member_weight: float = 0.05,
    stack_alpha: float = 1.0,
    export_predictions: bool = True,
    eval_dir: Path | None = None,
    elo_params: BaseballEloParams | None = None,
) -> dict[str, Any]:
    games = pd.read_parquet(games_path)
    table = build_training_table(games, form_window=form_window)
    table = attach_runs_strength(table, games, window=runs_strength_window)
    table = attach_poisson(table, games)
    table = attach_pythagorean(table, games)
    elo_params = elo_params or BaseballEloParams()
    table = attach_elo(table, games, params=elo_params)
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
    poisson = PoissonMember()
    poisson.fit(train_df)
    pythagorean = PythagoreanMember()
    pythagorean.fit(train_df)
    elo = EloMember(elo_params)
    elo.fit(train_df)

    train_games = games[
        games["season_start_year"].isin(train_seasons)
        & games["seasontype"].isin(train_seasontypes)
    ]
    _, elo_win_state, elo_offdef_state = fit_baseball_elo(train_games, params=elo_params)
    save_member_state(
        model_dir / "elo_member_state.json",
        win_state=elo_win_state,
        offdef_state=elo_offdef_state,
    )

    members: list[
        LgbmMember
        | HeuristicMember
        | RunsStrengthMember
        | PoissonMember
        | PythagoreanMember
        | EloMember
    ] = [
        lgbm,
        heuristic,
        runs_strength,
        poisson,
        pythagorean,
        elo,
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
            min_member_weight=min_member_weight,
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

    stacker, stack_val_fit_metrics = stack_fit_with_metrics(
        member_pred_list,
        actual_total_val,
        actual_margin_val,
        alpha=stack_alpha,
    )
    ensemble_stacked_val = stack_predict(member_pred_list, stacker)
    ensemble_stacked_test = stack_predict(list(test_preds.values()), stacker)

    member_names = [member.name for member in members]
    ensemble_payload = {
        "version": 2,
        "members": member_names,
        "weights": {"total": weights_total, "margin": weights_margin},
        "stacker": stacker,
        "winner_mode": "sign_margin",
        "val_metrics": val_tune_metrics,
        "stack_val_metrics": stack_val_fit_metrics,
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
        "ensemble_stacked": {
            "stacker_alpha": stack_alpha,
            "val_fit": stack_val_fit_metrics,
            "val": _metrics(
                ensemble_stacked_val.total, ensemble_stacked_val.margin, val_df
            ),
            "test": _metrics(
                ensemble_stacked_test.total, ensemble_stacked_test.margin, test_df
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

    if export_predictions:
        out_dir = eval_dir if eval_dir is not None else report_path.parent
        val_path = out_dir / "val_predictions.parquet"
        test_path = out_dir / "test_predictions.parquet"
        export_split_predictions(
            df=val_df,
            member_preds=val_preds,
            ensemble_equal=ensemble_equal_val,
            ensemble_weighted=ensemble_weighted_val,
            path=val_path,
            ensemble_stacked=ensemble_stacked_val,
        )
        export_split_predictions(
            df=test_df,
            member_preds=test_preds,
            ensemble_equal=ensemble_equal_test,
            ensemble_weighted=ensemble_weighted_test,
            path=test_path,
            ensemble_stacked=ensemble_stacked_test,
        )
        print(f"[mlb-pregame] Wrote {val_path} and {test_path}")

    return meta
