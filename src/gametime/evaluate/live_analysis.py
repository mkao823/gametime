from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from gametime.features.game_phase import LATE_GAME_PCT, assign_game_phase
from gametime.live.log import LivePredictionLogger


def add_prediction_errors(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["err_total"] = out["pred_total_final"] - out["total_final"]
    out["abs_err_total"] = out["err_total"].abs()
    if "naive_total_final" in out.columns:
        out["err_naive_total"] = out["naive_total_final"] - out["total_final"]
        out["abs_err_naive_total"] = out["err_naive_total"].abs()
    out["game_phase"] = assign_game_phase(
        out["pct_complete"], out["home_score"] - out["away_score"], out.get("period")
    )
    return out


def analyze_live_logs(log_dir: str | Path, report_dir: str | Path) -> dict[str, Any]:
    log_dir, report_dir = Path(log_dir), Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    labeled = LivePredictionLogger.load_labeled(log_dir)
    if labeled.empty:
        summary = {"status": "no_labeled_data", "hint": "Poll through final or check game_outcomes.parquet"}
        (report_dir / "summary.json").write_text(json.dumps(summary, indent=2))
        return summary
    labeled = add_prediction_errors(labeled)
    phase = labeled.groupby("game_phase", observed=True).agg(
        n=("abs_err_total", "count"),
        mae_total=("abs_err_total", "mean"),
        bias_total=("err_total", "mean"),
    )
    summary = {
        "status": "ok",
        "n_rows": len(labeled),
        "mae_total": float(labeled["abs_err_total"].mean()),
        "bias_total": float(labeled["err_total"].mean()),
        "by_phase": phase.reset_index().to_dict(orient="records"),
    }
    phase.to_csv(report_dir / "mae_by_phase.csv")
    labeled.to_parquet(report_dir / "labeled_predictions.parquet", index=False)
    (report_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return summary
