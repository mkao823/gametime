from __future__ import annotations

import pandas as pd

from gametime.features.game_phase import add_phase_features
from gametime.features.pace import add_multi_window_pace

REGULATION_MINUTES = 48.0  # NBA default; pass regulation_minutes= for other leagues


def add_model_features(
    snapshots: pd.DataFrame,
    interval_seconds: int = 60,
    rolling_window_seconds: int = 300,
    long_window_seconds: int = 600,
    regulation_minutes: float = REGULATION_MINUTES,
    period_length_sec: int = 720,
) -> pd.DataFrame:
    df = snapshots.copy()
    elapsed_min = (df["sec_elapsed_game"] / 60.0).clip(lower=0.5)
    remaining_min = (regulation_minutes - elapsed_min).clip(lower=0.0)
    df["pace_total"] = df["total_score"] / elapsed_min * regulation_minutes
    df["home_ppm"] = df["home_score"] / elapsed_min
    df["away_ppm"] = df["away_score"] / elapsed_min
    df["naive_total_final"] = df["total_score"] + df["pace_total"] * (remaining_min / regulation_minutes)
    df["naive_remaining_total"] = df["naive_total_final"] - df["total_score"]
    steps = max(1, int(rolling_window_seconds / interval_seconds))
    df = df.sort_values(["game_id", "sec_elapsed_game"])
    df["total_score_lag"] = df.groupby("game_id")["total_score"].shift(steps)
    window_min = steps * interval_seconds / 60.0
    df["pace_recent"] = (df["total_score"] - df["total_score_lag"]) / window_min * regulation_minutes
    df["pace_recent"] = df["pace_recent"].fillna(df["pace_total"])
    df["naive_recent_total_final"] = df["total_score"] + df["pace_recent"] * (
        remaining_min / regulation_minutes
    )
    df = add_multi_window_pace(
        df,
        interval_seconds=interval_seconds,
        rolling_window_seconds=rolling_window_seconds,
        long_window_seconds=long_window_seconds,
        regulation_minutes=regulation_minutes,
        period_length_sec=period_length_sec,
    )
    return add_phase_features(df)
