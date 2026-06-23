from __future__ import annotations

import re

import numpy as np
import pandas as pd

SCORE_PATTERN = re.compile(r"^\s*(\d+)\s*[-–]\s*(\d+)\s*$")
PERIOD_LENGTH_SEC = 720
REGULATION_PERIODS = 4


def parse_clock_to_seconds(clock: str) -> float | None:
    if pd.isna(clock) or not str(clock).strip():
        return None
    text = str(clock).strip()
    if ":" not in text:
        return None
    parts = text.split(":")
    try:
        return int(parts[0]) * 60 + float(parts[1])
    except (ValueError, IndexError):
        return None


def parse_score_pair(score: str) -> tuple[float, float] | None:
    if pd.isna(score):
        return None
    text = str(score).strip().upper()
    if text in ("", "TIE"):
        return None
    m = SCORE_PATTERN.match(text)
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def normalize_nbastats_pbp(
    df: pd.DataFrame,
    *,
    period_length_sec: int = PERIOD_LENGTH_SEC,
    regulation_periods: int = REGULATION_PERIODS,
) -> pd.DataFrame:
    required = {"GAME_ID", "EVENTNUM", "PERIOD", "PCTIMESTRING", "SCORE"}
    if missing := required - set(df.columns):
        raise ValueError(f"Missing columns: {missing}")

    out = df.rename(
        columns={
            "GAME_ID": "game_id",
            "EVENTNUM": "event_num",
            "PERIOD": "period",
            "PCTIMESTRING": "clock",
            "SCORE": "score_raw",
        }
    ).copy()
    out["game_id"] = out["game_id"].astype(str)
    out["event_num"] = pd.to_numeric(out["event_num"], errors="coerce")
    out["period"] = pd.to_numeric(out["period"], errors="coerce").astype("Int64")
    out["sec_remaining_period"] = out["clock"].map(parse_clock_to_seconds)
    out[["away_score", "home_score"]] = out["score_raw"].apply(
        lambda s: pd.Series(parse_score_pair(s) or (np.nan, np.nan))
    )
    out = out.sort_values(["game_id", "event_num"]).reset_index(drop=True)
    for col in ("away_score", "home_score"):
        out[col] = out.groupby("game_id")[col].ffill()
    out["sec_elapsed_period"] = period_length_sec - out["sec_remaining_period"]
    out["sec_elapsed_game"] = (out["period"].fillna(1).astype(int) - 1) * period_length_sec + out[
        "sec_elapsed_period"
    ].fillna(0)
    out["sec_remaining_game"] = np.maximum(
        0.0, regulation_periods * period_length_sec - out["sec_elapsed_game"]
    )
    out["total_score"] = out["away_score"] + out["home_score"]
    out["score_diff"] = out["home_score"] - out["away_score"]
    return out
