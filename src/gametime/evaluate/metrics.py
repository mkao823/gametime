from __future__ import annotations

from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from gametime.models.constants import FEATURE_COLUMNS, TARGET_REMAINING_MARGIN, TARGET_REMAINING_TOTAL


def predict_frame(df: pd.DataFrame, model_dir: str | Path) -> pd.DataFrame:
    model_dir = Path(model_dir)
    b_total = lgb.Booster(model_file=str(model_dir / f"{TARGET_REMAINING_TOTAL}.txt"))
    b_margin = lgb.Booster(model_file=str(model_dir / f"{TARGET_REMAINING_MARGIN}.txt"))
    rem_total = b_total.predict(df[FEATURE_COLUMNS])
    rem_margin = b_margin.predict(df[FEATURE_COLUMNS])
    out = df.copy()
    out["pred_remaining_total"] = rem_total
    out["pred_remaining_margin"] = rem_margin
    out["pred_total_final"] = out["total_score"] + rem_total
    out["pred_margin_final"] = out["score_diff"] + rem_margin
    out["pred_home_final"] = (out["pred_total_final"] + out["pred_margin_final"]) / 2.0
    out["pred_away_final"] = (out["pred_total_final"] - out["pred_margin_final"]) / 2.0
    return out


def evaluate_predictions(pred: pd.DataFrame) -> dict[str, float]:
    metrics = {
        "mae_total_final": float(np.mean(np.abs(pred["pred_total_final"] - pred["total_final"]))),
        "mae_home_final": float(np.mean(np.abs(pred["pred_home_final"] - pred["home_final"]))),
        "mae_away_final": float(np.mean(np.abs(pred["pred_away_final"] - pred["away_final"]))),
        "bias_total": float(np.mean(pred["pred_total_final"] - pred["total_final"])),
    }
    if "naive_total_final" in pred.columns:
        metrics["mae_naive_total_final"] = float(
            np.mean(np.abs(pred["naive_total_final"] - pred["total_final"]))
        )
    return metrics


def mae_by_phase(pred: pd.DataFrame) -> pd.DataFrame:
    if "game_phase" not in pred.columns:
        return pd.DataFrame()
    rows = []
    for phase, g in pred.groupby("game_phase", observed=True):
        rows.append(
            {
                "game_phase": phase,
                "n": len(g),
                "mae_total": np.mean(np.abs(g["pred_total_final"] - g["total_final"])),
                "bias_total": np.mean(g["pred_total_final"] - g["total_final"]),
                "mae_naive": np.mean(np.abs(g["naive_total_final"] - g["total_final"]))
                if "naive_total_final" in g.columns
                else np.nan,
            }
        )
    return pd.DataFrame(rows)


def mae_by_season(pred: pd.DataFrame) -> pd.DataFrame:
    if "season_start_year" not in pred.columns:
        return pd.DataFrame()
    rows = []
    for (season, st), g in pred.groupby(["season_start_year", "seasontype"], observed=True):
        rows.append(
            {
                "season_start_year": season,
                "seasontype": st,
                "n": len(g),
                "n_games": g["game_id"].nunique(),
                "mae_total": np.mean(np.abs(g["pred_total_final"] - g["total_final"])),
                "bias_total": np.mean(g["pred_total_final"] - g["total_final"]),
            }
        )
    return pd.DataFrame(rows)
