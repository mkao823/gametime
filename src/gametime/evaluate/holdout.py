from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from gametime.data.game_meta import annotate_games, filter_games
from gametime.evaluate.metrics import evaluate_predictions, mae_by_phase, mae_by_season, predict_frame


def run_holdout_eval(
    snapshots: pd.DataFrame,
    model_dir: str | Path,
    cfg: dict,
    report_dir: str | Path,
) -> dict[str, Any]:
    """Evaluate on held-out test slice (default: playoffs) with by-phase and by-season tables."""
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    eval_cfg = cfg.get("evaluate", {})
    train_cfg = cfg.get("train", {})

    test_seasons = eval_cfg.get("test_seasons") or train_cfg.get("test_seasons") or (
        [eval_cfg.get("test_season", train_cfg.get("test_season"))]
        if eval_cfg.get("test_season") or train_cfg.get("test_season")
        else None
    )
    test = filter_games(
        snapshots,
        seasons=test_seasons,
        seasontypes=[eval_cfg.get("test_seasontype", train_cfg.get("test_seasontype", "po"))],
    )
    if test.empty:
        summary = {
            "status": "empty_test_set",
            "hint": "Rebuild snapshots with playoff data (seasontype: both) or adjust test_season.",
        }
        (report_dir / "summary.json").write_text(json.dumps(summary, indent=2))
        return summary

    pred = predict_frame(test, model_dir)
    if "season_start_year" not in pred.columns:
        pred = annotate_games(pred)
    overall = evaluate_predictions(pred)

    summary: dict[str, Any] = {
        "status": "ok",
        "test_seasons": test_seasons,
        "test_seasontype": eval_cfg.get("test_seasontype", train_cfg.get("test_seasontype", "po")),
        "n_rows": len(pred),
        "n_games": int(pred["game_id"].nunique()),
        "overall": overall,
    }

    if eval_cfg.get("by_phase", True):
        phase_df = mae_by_phase(pred)
        phase_df.to_csv(report_dir / "mae_by_phase.csv", index=False)
        summary["by_phase"] = phase_df.to_dict(orient="records")

    if eval_cfg.get("by_season", True):
        season_df = mae_by_season(pred)
        season_df.to_csv(report_dir / "mae_by_season.csv", index=False)
        summary["by_season"] = season_df.to_dict(orient="records")

    pred.to_parquet(report_dir / "test_predictions.parquet", index=False)
    (report_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return summary
