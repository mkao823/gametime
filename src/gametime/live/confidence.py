"""Crunch-time confidence band for predicted final total.

Uses playoff hold-out MAE in the crunch phase (~3.7 pts) as a half-width
around the displayed prediction. The floor is the current game total (final
cannot be below points already scored).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from gametime.features.game_phase import CRUNCH_PCT


@dataclass
class CrunchTotalRange:
    low: float
    high: float
    half_width: float

    def format(self) -> str:
        return f"{self.low:.0f}–{self.high:.0f}"


def crunch_total_range(
    pred_total: float,
    current_total: float,
    pct_complete: float,
    *,
    crunch_pct: float = CRUNCH_PCT,
    half_width: float = 3.7,
) -> Optional[CrunchTotalRange]:
    if pct_complete < crunch_pct:
        return None
    low = max(float(current_total), float(pred_total) - half_width)
    high = float(pred_total) + half_width
    if low > high:
        low = high
    return CrunchTotalRange(low=low, high=high, half_width=half_width)
