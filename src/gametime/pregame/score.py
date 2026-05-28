"""Batch and single-row pregame model scoring (shared by predict + join)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import lightgbm as lgb
import pandas as pd

from gametime.pregame.calibration import (
    MarginBandCalibration,
    MarginCalibration,
    load_band_calibration,
    load_calibration,
)
from gametime.pregame.constants import (
    TARGET_BLOWOUT,
    TARGET_MARGIN,
    TARGET_MARGIN_P10,
    TARGET_MARGIN_P90,
    TARGET_TOTAL,
)
from gametime.pregame.features import FEATURE_COLUMNS


def load_pregame_boosters(model_dir: Path) -> dict[str, lgb.Booster]:
    model_dir = Path(model_dir)
    boosters: dict[str, lgb.Booster] = {
        TARGET_TOTAL: lgb.Booster(model_file=str(model_dir / f"{TARGET_TOTAL}.txt")),
        TARGET_MARGIN: lgb.Booster(model_file=str(model_dir / f"{TARGET_MARGIN}.txt")),
    }
    for name in (TARGET_BLOWOUT, TARGET_MARGIN_P10, TARGET_MARGIN_P90):
        path = model_dir / f"{name}.txt"
        if path.exists():
            boosters[name] = lgb.Booster(model_file=str(path))
    return boosters


def score_feature_frame(
    X: pd.DataFrame,
    boosters: dict[str, lgb.Booster],
    *,
    calibration: Optional[MarginCalibration] = None,
    band_calibration: Optional[MarginBandCalibration] = None,
    use_calibrated_margin: bool = True,
) -> pd.DataFrame:
    """Return pregame total/margin/uncertainty columns aligned to X.index."""
    out = pd.DataFrame(index=X.index)
    out["pregame_pred_total"] = boosters[TARGET_TOTAL].predict(X)
    margin_raw = boosters[TARGET_MARGIN].predict(X)
    out["pregame_pred_margin_raw"] = margin_raw
    if TARGET_BLOWOUT in boosters:
        out["pregame_blowout_prob"] = boosters[TARGET_BLOWOUT].predict(X)
    else:
        out["pregame_blowout_prob"] = 0.0
    if TARGET_MARGIN_P10 in boosters:
        out["pregame_margin_low"] = boosters[TARGET_MARGIN_P10].predict(X)
    else:
        out["pregame_margin_low"] = margin_raw - 8.0
    if TARGET_MARGIN_P90 in boosters:
        out["pregame_margin_high"] = boosters[TARGET_MARGIN_P90].predict(X)
    else:
        out["pregame_margin_high"] = margin_raw + 8.0
    if band_calibration is not None:
        scaled = [
            band_calibration.apply(lo, hi)
            for lo, hi in zip(out["pregame_margin_low"], out["pregame_margin_high"])
        ]
        out["pregame_margin_low"] = [x[0] for x in scaled]
        out["pregame_margin_high"] = [x[1] for x in scaled]
    out["pregame_margin_band_width"] = out["pregame_margin_high"] - out["pregame_margin_low"]
    if calibration is not None and use_calibrated_margin:
        out["pregame_pred_margin"] = [
            calibration.apply(m, p)
            for m, p in zip(margin_raw, out["pregame_blowout_prob"])
        ]
    else:
        out["pregame_pred_margin"] = margin_raw
    return out


def load_calibration_if_present(model_dir: Path) -> Optional[MarginCalibration]:
    path = Path(model_dir) / "calibration.json"
    return load_calibration(path) if path.exists() else None


def load_band_calibration_if_present(model_dir: Path) -> Optional[MarginBandCalibration]:
    path = Path(model_dir) / "margin_band.json"
    return load_band_calibration(path) if path.exists() else None
