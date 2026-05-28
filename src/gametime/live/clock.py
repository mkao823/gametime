from __future__ import annotations

import re

from gametime.data.pbp import PERIOD_LENGTH_SEC, REGULATION_PERIODS, parse_clock_to_seconds

ISO_CLOCK = re.compile(r"^PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$", re.I)
REGULATION_SECONDS = REGULATION_PERIODS * PERIOD_LENGTH_SEC
OT_PERIOD_LENGTH_SEC = 300


def parse_iso_clock(clock: str) -> float | None:
    if not clock or not str(clock).strip():
        return None
    text = str(clock).strip().upper()
    m = ISO_CLOCK.match(text)
    if not m:
        return parse_clock_to_seconds(text)
    return int(m.group(1) or 0) * 60 + float(m.group(2) or 0)


def game_seconds_elapsed(period: int, sec_remaining_period: float, period_length: int = PERIOD_LENGTH_SEC) -> float:
    period = max(1, int(period))
    elapsed = period_length - max(0.0, float(sec_remaining_period))
    if period <= REGULATION_PERIODS:
        return (period - 1) * period_length + elapsed
    ot = period - REGULATION_PERIODS
    return REGULATION_PERIODS * period_length + (ot - 1) * OT_PERIOD_LENGTH_SEC + elapsed


def game_seconds_remaining_regulation(sec_elapsed: float) -> float:
    return max(0.0, REGULATION_SECONDS - sec_elapsed)
