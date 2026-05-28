"""Append pre-game predictions to a parquet log for later comparison with actuals."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from gametime.pregame.predict import PregamePrediction


def log_pregame_prediction(
    log_dir: str | Path,
    pred: PregamePrediction,
    *,
    game_id: Optional[str] = None,
    matchup: Optional[str] = None,
) -> Path:
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "pregame_predictions.parquet"

    record = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "game_id": game_id,
        "matchup": matchup or f"{pred.away_tricode} @ {pred.home_tricode}",
        "home_tricode": pred.home_tricode,
        "away_tricode": pred.away_tricode,
        "variant": pred.variant,
        "is_playoff": int(pred.is_playoff),
        "elo_home": pred.elo_home,
        "elo_away": pred.elo_away,
        "pred_total": pred.pred_total,
        "pred_margin": pred.pred_margin,
        "pred_home_final": pred.pred_home_final,
        "pred_away_final": pred.pred_away_final,
        "winner_tricode": pred.winner_tricode,
        "win_prob_home": pred.win_prob_home,
        "home_form_n": pred.home_form_n,
        "away_form_n": pred.away_form_n,
        "vegas_weight": pred.vegas_weight,
        "vegas_spread_home": pred.vegas.get("spread_home") if pred.vegas else None,
        "vegas_total": pred.vegas.get("total") if pred.vegas else None,
        "vegas_source": pred.vegas.get("source") if pred.vegas else None,
        "model_only_total": pred.model_only.get("pred_total") if pred.model_only else None,
        "model_only_margin": pred.model_only.get("pred_margin") if pred.model_only else None,
        "model_only_winner": pred.model_only.get("winner") if pred.model_only else None,
        "pred_margin_raw": pred.pred_margin_raw,
        "pred_margin_calibrated": pred.pred_margin_calibrated,
        "margin_low": pred.margin_low,
        "margin_high": pred.margin_high,
        "blowout_prob": pred.blowout_prob,
    }

    row = pd.DataFrame([record])
    if path.exists():
        existing = pd.read_parquet(path)
        all_cols = list(dict.fromkeys([*existing.columns, *row.columns]))
        existing = existing.reindex(columns=all_cols)
        row = row.reindex(columns=all_cols)
        row = pd.concat([existing, row], ignore_index=True, copy=False)
    row.to_parquet(path, index=False)
    return path


def write_pregame_json(json_path: Path, pred: PregamePrediction) -> Path:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(pred.as_dict(), indent=2, default=float))
    return json_path
