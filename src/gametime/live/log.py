from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from gametime.live.fetch import LiveGameSnapshot
from gametime.live.inference import LivePrediction
from gametime.models.constants import FEATURE_COLUMNS


class LivePredictionLogger:
    def __init__(self, log_dir: str | Path, *, model_tag: str = "lightgbm"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.predictions_path = self.log_dir / "predictions.parquet"
        self.outcomes_path = self.log_dir / "game_outcomes.parquet"
        self.model_tag = model_tag

    def log_prediction(
        self, snap, pred, feature_row, *, naive_only: bool = False, kalshi=None
    ) -> None:
        record = {
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "game_id": snap.game_id,
            "matchup": pred.matchup,
            "period": snap.period,
            "pct_complete": pred.pct_complete,
            "home_score": snap.home_score,
            "away_score": snap.away_score,
            "model_type": "naive" if naive_only else self.model_tag,
            "pred_total_final": pred.pred_total_final,
            "pred_home_final": pred.pred_home_final,
            "pred_away_final": pred.pred_away_final,
            "naive_total_final": pred.naive_total_final,
            "raw_pred_total_final": pred.raw_pred_total_final,
            "raw_pred_home_final": pred.raw_pred_home_final,
            "raw_pred_away_final": pred.raw_pred_away_final,
            "prior_total": pred.prior_total,
            "prior_margin": pred.prior_margin,
            "prior_weight": pred.prior_weight,
            "prior_source": pred.prior_source,
            "kalshi_total": kalshi.total if kalshi is not None else None,
            "kalshi_spread_home": kalshi.spread_home if kalshi is not None else None,
            "total_low": pred.crunch_range.low if pred.crunch_range else None,
            "total_high": pred.crunch_range.high if pred.crunch_range else None,
        }
        for col in FEATURE_COLUMNS:
            record[f"feat_{col}"] = float(feature_row[col])
        _append_parquet(self.predictions_path, record)

    def log_game_outcome(self, snap: LiveGameSnapshot) -> None:
        _append_parquet(
            self.outcomes_path,
            {
                "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                "game_id": snap.game_id,
                "home_final": snap.home_score,
                "away_final": snap.away_score,
                "total_final": snap.home_score + snap.away_score,
            },
            dedupe_key="game_id",
        )

    @staticmethod
    def load_predictions(log_dir: str | Path) -> pd.DataFrame:
        path = Path(log_dir) / "predictions.parquet"
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()

    @staticmethod
    def load_outcomes(log_dir: str | Path) -> pd.DataFrame:
        path = Path(log_dir) / "game_outcomes.parquet"
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()

    @staticmethod
    def load_labeled(log_dir: str | Path) -> pd.DataFrame:
        preds = LivePredictionLogger.load_predictions(log_dir)
        out = LivePredictionLogger.load_outcomes(log_dir)
        if preds.empty or out.empty:
            return pd.DataFrame()
        return preds.merge(out, on="game_id", suffixes=("", "_o"))


def _append_parquet(path: Path, record: dict, dedupe_key: Optional[str] = None) -> None:
    if path.exists():
        existing = pd.read_parquet(path)
        if dedupe_key and dedupe_key in existing.columns and record[dedupe_key] in existing[dedupe_key].values:
            existing = existing[existing[dedupe_key] != record[dedupe_key]]
        df = pd.DataFrame(existing.to_dict("records") + [record])
    else:
        df = pd.DataFrame([record])
    df.to_parquet(path, index=False)
