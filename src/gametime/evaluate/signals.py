from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from gametime.data.game_meta import annotate_games, filter_games
from gametime.evaluate.metrics import predict_frame


def _local_extrema(series: pd.Series, window: int, kind: str) -> pd.Series:
    """Rolling local max (peak) or min (trough)."""
    if kind == "peak":
        roll = series.rolling(window, center=True, min_periods=1).max()
        return series >= roll - 1e-6
    roll = series.rolling(window, center=True, min_periods=1).min()
    return series <= roll + 1e-6


def label_signal_rows(
    pred: pd.DataFrame,
    *,
    window: int = 5,
    min_peak_delta: float = 3.0,
    sporadic_pace_std: float = 8.0,
) -> pd.DataFrame:
    """
    Tag peaks/troughs on pred_total_final per game.

    Success (no market line):
      under@peak  -> actual_final < pred_total at peak
      over@trough -> actual_final > pred_total at trough
    """
    out = pred.sort_values(["game_id", "sec_elapsed_game"]).copy()
    tags = []
    for game_id, g in out.groupby("game_id"):
        g = g.copy()
        med = g["pred_total_final"].median()
        g["is_peak"] = _local_extrema(g["pred_total_final"], window, "peak") & (
            g["pred_total_final"] >= med + min_peak_delta
        )
        g["is_trough"] = _local_extrema(g["pred_total_final"], window, "trough") & (
            g["pred_total_final"] <= med - min_peak_delta
        )
        if "pace_recent" in g.columns:
            g["pace_volatile"] = (
                g.groupby("game_id")["pace_recent"].transform(lambda s: s.rolling(5, min_periods=2).std())
                > sporadic_pace_std
            )
        else:
            g["pace_volatile"] = False
        g["under_hit"] = g["total_final"] < g["pred_total_final"]
        g["over_hit"] = g["total_final"] > g["pred_total_final"]
        g["under_signal_ok"] = g["is_peak"] & g["under_hit"]
        g["over_signal_ok"] = g["is_trough"] & g["over_hit"]
        g["no_bet_sporadic"] = g["pace_volatile"] | (g.get("game_phase") == "crunch")
        tags.append(g)
    return pd.concat(tags, ignore_index=True)


def summarize_signals(tagged: pd.DataFrame) -> dict[str, Any]:
    def _rate(mask: pd.Series, hit: pd.Series) -> dict[str, float]:
        sub = tagged[mask & ~tagged["no_bet_sporadic"]]
        if len(sub) == 0:
            return {"n": 0, "hit_rate": np.nan}
        return {"n": int(len(sub)), "hit_rate": float(hit[sub.index].mean())}

    baseline_under = float((tagged["total_final"] < tagged["pred_total_final"]).mean())
    baseline_over = float((tagged["total_final"] > tagged["pred_total_final"]).mean())

    return {
        "n_rows": len(tagged),
        "n_games": int(tagged["game_id"].nunique()),
        "baseline_under_rate": baseline_under,
        "baseline_over_rate": baseline_over,
        "under_at_peak": _rate(tagged["is_peak"], tagged["under_signal_ok"]),
        "over_at_trough": _rate(tagged["is_trough"], tagged["over_signal_ok"]),
        "by_phase": tagged.groupby("game_phase", observed=True)
        .agg(
            n=("game_id", "count"),
            under_peak_hits=("under_signal_ok", "sum"),
            peak_n=("is_peak", "sum"),
        )
        .reset_index()
        .to_dict(orient="records")
        if "game_phase" in tagged.columns
        else [],
    }


def run_signal_backtest(
    snapshots: pd.DataFrame,
    model_dir: str | Path,
    cfg: dict,
    report_dir: str | Path,
) -> dict[str, Any]:
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    sig_cfg = cfg.get("signals", {})
    eval_cfg = cfg.get("evaluate", {})
    train_cfg = cfg.get("train", {})

    test_seasons = eval_cfg.get("test_seasons") or train_cfg.get("test_seasons") or (
        [train_cfg.get("test_season")] if train_cfg.get("test_season") else None
    )
    test = filter_games(
        snapshots,
        seasons=test_seasons,
        seasontypes=[eval_cfg.get("test_seasontype", train_cfg.get("test_seasontype", "po"))],
    )
    if test.empty:
        summary = {"status": "empty_test_set"}
        (report_dir / "summary.json").write_text(json.dumps(summary, indent=2))
        return summary

    pred = predict_frame(test, model_dir)
    pred = annotate_games(pred)
    tagged = label_signal_rows(
        pred,
        window=sig_cfg.get("peak_window_polls", 5),
        min_peak_delta=sig_cfg.get("min_peak_delta", 3.0),
        sporadic_pace_std=sig_cfg.get("sporadic_pace_std", 8.0),
    )
    summary = {"status": "ok", **summarize_signals(tagged)}
    tagged.to_parquet(report_dir / "tagged_signals.parquet", index=False)
    (report_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return summary
