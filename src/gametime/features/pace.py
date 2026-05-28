"""Pace features shared by snapshot build (historical) and live inference."""
from __future__ import annotations

import pandas as pd

REGULATION_MINUTES = 48.0
PERIOD_SECONDS = 720


def pace_from_points(total_now: float, total_lag: float, window_minutes: float) -> float:
    return (total_now - total_lag) / max(window_minutes, 1e-6) * REGULATION_MINUTES


def pace_full_game(total: float, elapsed_minutes: float) -> float:
    return total / max(elapsed_minutes, 0.5) * REGULATION_MINUTES


from typing import Optional


def pace_first_quarter(total: float, sec_elapsed_game: float, q1_final_total: Optional[float]) -> float:
    """Q1 scoring rate; after Q1 ends use frozen Q1 total (12 regulation minutes)."""
    if sec_elapsed_game <= PERIOD_SECONDS:
        return pace_full_game(total, sec_elapsed_game / 60.0)
    if q1_final_total is not None:
        return q1_final_total / 12.0 * REGULATION_MINUTES
    return pace_full_game(total, sec_elapsed_game / 60.0)


def add_multi_window_pace(
    df: pd.DataFrame,
    *,
    interval_seconds: int = 60,
    rolling_window_seconds: int = 300,
    long_window_seconds: int = 600,
    regulation_minutes: float = REGULATION_MINUTES,
    period_length_sec: int = PERIOD_SECONDS,
) -> pd.DataFrame:
    """Add pace_10min, pace_1q, pace_vs_recent to a snapshot frame (sorted by game_id, sec)."""
    out = df.sort_values(["game_id", "sec_elapsed_game"]).copy()
    short_steps = max(1, int(rolling_window_seconds / interval_seconds))
    long_steps = max(1, int(long_window_seconds / interval_seconds))
    short_min = short_steps * interval_seconds / 60.0
    long_min = long_steps * interval_seconds / 60.0

    lag_short = out.groupby("game_id")["total_score"].shift(short_steps)
    lag_long = out.groupby("game_id")["total_score"].shift(long_steps)
    out["pace_10min"] = (
        (out["total_score"] - lag_long) / long_min * regulation_minutes
    ).fillna(out["pace_total"])
    out["pace_vs_recent"] = out["pace_recent"] - out["pace_total"]

    q1_period_minutes = period_length_sec / 60.0
    q1_totals = (
        out.loc[out["sec_elapsed_game"] == period_length_sec, ["game_id", "total_score"]]
        .drop_duplicates("game_id")
        .set_index("game_id")["total_score"]
    )
    in_q1 = out["sec_elapsed_game"] <= period_length_sec
    elapsed_min_q1 = (out["sec_elapsed_game"] / 60.0).clip(lower=0.5)
    out["pace_1q"] = out["pace_total"]
    out.loc[in_q1, "pace_1q"] = (
        out.loc[in_q1, "total_score"] / elapsed_min_q1[in_q1] * regulation_minutes
    )
    after_q1 = ~in_q1
    mapped = out.loc[after_q1, "game_id"].map(q1_totals)
    out.loc[after_q1, "pace_1q"] = mapped / q1_period_minutes * regulation_minutes
    out["pace_1q"] = out["pace_1q"].fillna(out["pace_total"])
    return out
