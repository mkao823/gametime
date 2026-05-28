from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Optional

import pandas as pd

from gametime.features.game_phase import add_phase_features
from gametime.features.pace import pace_first_quarter, pace_from_points, pace_full_game
from gametime.live.clock import game_seconds_elapsed, game_seconds_remaining_regulation
from gametime.live.fetch import LiveGameSnapshot
from gametime.features.pregame_join import PREGAME_FEATURE_DEFAULTS
from gametime.models.constants import FEATURE_COLUMNS

REGULATION_MINUTES = 48.0


@dataclass
class ScoreHistory:
    window_seconds: int = 300
    long_window_seconds: int = 600
    points: Deque[tuple[float, float]] = field(default_factory=deque)
    last_period: int = 0
    q1_total: Optional[float] = None

    def add(self, sec_elapsed: float, total_score: float, period: int) -> None:
        if period == 1:
            self.q1_total = total_score
        self.last_period = period
        self.points.append((sec_elapsed, total_score))
        cutoff = sec_elapsed - self.long_window_seconds
        while self.points and self.points[0][0] < cutoff:
            self.points.popleft()

    def total_at_lag(self, sec_elapsed: float, lag_seconds: float) -> Optional[float]:
        target = sec_elapsed - lag_seconds
        candidate = None
        for t, total in self.points:
            if t <= target:
                candidate = total
        return candidate

    def pace_at_lag(
        self, sec_elapsed: float, total_score: float, lag_seconds: float, fallback: float
    ) -> float:
        lag_total = self.total_at_lag(sec_elapsed, lag_seconds)
        if lag_total is None:
            return fallback
        return pace_from_points(total_score, lag_total, lag_seconds / 60.0)


def snapshot_to_feature_row(
    snap: LiveGameSnapshot,
    history: Optional[ScoreHistory] = None,
    rolling_window_seconds: int = 300,
    long_window_seconds: int = 600,
) -> pd.Series:
    sec_elapsed = game_seconds_elapsed(snap.period, snap.sec_remaining_period)
    sec_remaining = game_seconds_remaining_regulation(sec_elapsed)
    pct_complete = min(1.0, sec_elapsed / 2880.0)
    total = snap.home_score + snap.away_score
    elapsed_min = max(sec_elapsed / 60.0, 0.5)
    remaining_min = max(REGULATION_MINUTES - elapsed_min, 0.0)
    pace_total = pace_full_game(total, elapsed_min)
    pace_recent = pace_total
    pace_10min = pace_total
    if history:
        history.add(sec_elapsed, total, snap.period)
        pace_recent = history.pace_at_lag(
            sec_elapsed, total, rolling_window_seconds, pace_total
        )
        pace_10min = history.pace_at_lag(
            sec_elapsed, total, long_window_seconds, pace_total
        )
    q1_final = history.q1_total if history and snap.period > 1 else None
    pace_1q = pace_first_quarter(total, sec_elapsed, q1_final)

    row = {
        "game_id": snap.game_id,
        "sec_elapsed_game": sec_elapsed,
        "sec_remaining_game": sec_remaining,
        "pct_complete": pct_complete,
        "period": snap.period,
        "home_score": snap.home_score,
        "away_score": snap.away_score,
        "total_score": total,
        "score_diff": snap.home_score - snap.away_score,
        "pace_total": pace_total,
        "home_ppm": snap.home_score / elapsed_min,
        "away_ppm": snap.away_score / elapsed_min,
        "pace_recent": pace_recent,
        "pace_10min": pace_10min,
        "pace_1q": pace_1q,
        "pace_vs_recent": pace_recent - pace_total,
        "naive_remaining_total": (total + pace_total * (remaining_min / REGULATION_MINUTES)) - total,
        "naive_recent_total_final": total + pace_recent * (remaining_min / REGULATION_MINUTES),
    }
    df = add_phase_features(pd.DataFrame([row]))
    series = df.iloc[0].copy()
    for col, default in PREGAME_FEATURE_DEFAULTS.items():
        if col not in series.index or pd.isna(series[col]):
            series[col] = default
    if "naive_vs_pregame" in FEATURE_COLUMNS:
        series["naive_vs_pregame"] = float(series["naive_recent_total_final"]) - float(
            series["pregame_pred_total"]
        )
    for col in FEATURE_COLUMNS:
        series[col] = float(series[col])
    return series
