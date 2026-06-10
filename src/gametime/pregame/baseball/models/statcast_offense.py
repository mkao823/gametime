"""Statcast team offense attach + optional ensemble member (W12)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from gametime.ingest.mlb_statcast_offense import (
    LEAGUE_BARREL_PCT,
    LEAGUE_HARD_HIT_PCT,
    LEAGUE_XWOBA,
    STATCAST_OFFENSE_COLUMNS,
)
from gametime.pregame.baseball.models.base import BaseballMemberModel
from gametime.pregame.baseball.prediction import MemberPrediction

LEAGUE_TOTAL = 8.7
XWOBA_TO_TOTAL = 14.0
XWOBA_TO_MARGIN = 10.0
BARREL_TO_TOTAL = 6.0
BARREL_TO_MARGIN = 4.0


def attach_statcast_offense(
    table: pd.DataFrame, statcast_games: pd.DataFrame
) -> pd.DataFrame:
    out = table.copy()
    drop_cols = [
        "home_xwoba_roll", "away_xwoba_roll",
        "home_barrel_pct_roll", "away_barrel_pct_roll",
        "home_hard_hit_pct_roll", "away_hard_hit_pct_roll",
        "xwoba_off_diff", "has_statcast_offense",
    ]
    out = out.drop(columns=[c for c in drop_cols if c in out.columns], errors="ignore")

    sg = statcast_games.copy() if statcast_games is not None else pd.DataFrame()
    if not sg.empty:
        cols = [c for c in STATCAST_OFFENSE_COLUMNS if c in sg.columns]
        out = out.merge(sg[cols], on="game_id", how="left")

    defaults = (
        ("home_xwoba_roll", LEAGUE_XWOBA),
        ("away_xwoba_roll", LEAGUE_XWOBA),
        ("home_barrel_pct_roll", LEAGUE_BARREL_PCT),
        ("away_barrel_pct_roll", LEAGUE_BARREL_PCT),
        ("home_hard_hit_pct_roll", LEAGUE_HARD_HIT_PCT),
        ("away_hard_hit_pct_roll", LEAGUE_HARD_HIT_PCT),
        ("xwoba_off_diff", 0.0),
        ("has_statcast_offense", 0),
    )
    for col, default in defaults:
        if col not in out.columns:
            out[col] = default
        else:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(default)

    out["has_statcast_offense"] = out["has_statcast_offense"].fillna(0).astype(int)
    if sg.empty:
        out["xwoba_off_diff"] = out["home_xwoba_roll"] - out["away_xwoba_roll"]
    return out


def latest_statcast_offense_columns(
    *,
    home: str,
    away: str,
    games: pd.DataFrame,
    statcast_games: pd.DataFrame,
) -> dict[str, float | int]:
    if statcast_games.empty or games.empty:
        return {
            "home_xwoba_roll": LEAGUE_XWOBA,
            "away_xwoba_roll": LEAGUE_XWOBA,
            "home_barrel_pct_roll": LEAGUE_BARREL_PCT,
            "away_barrel_pct_roll": LEAGUE_BARREL_PCT,
            "home_hard_hit_pct_roll": LEAGUE_HARD_HIT_PCT,
            "away_hard_hit_pct_roll": LEAGUE_HARD_HIT_PCT,
            "xwoba_off_diff": 0.0,
            "has_statcast_offense": 0,
        }
    merged = statcast_games.merge(
        games[["game_id", "game_date", "home_team", "away_team"]], on="game_id"
    )
    merged["game_date"] = pd.to_datetime(merged["game_date"])

    def _latest(team: str, prefix: str) -> pd.Series | None:
        home_rows = merged[merged["home_team"] == team.upper()].sort_values("game_date")
        away_rows = merged[merged["away_team"] == team.upper()].sort_values("game_date")
        if not home_rows.empty:
            return home_rows.iloc[-1]
        if not away_rows.empty:
            return away_rows.iloc[-1]
        return None

    h = _latest(home, "home")
    a = _latest(away, "away")
    home_x = float(h["home_xwoba_roll"]) if h is not None else LEAGUE_XWOBA
    away_x = float(a["away_xwoba_roll"]) if a is not None else LEAGUE_XWOBA
    home_b = float(h["home_barrel_pct_roll"]) if h is not None else LEAGUE_BARREL_PCT
    away_b = float(a["away_barrel_pct_roll"]) if a is not None else LEAGUE_BARREL_PCT
    home_hh = float(h["home_hard_hit_pct_roll"]) if h is not None else LEAGUE_HARD_HIT_PCT
    away_hh = float(a["away_hard_hit_pct_roll"]) if a is not None else LEAGUE_HARD_HIT_PCT
    has_h = int(h.get("has_statcast_offense", 0)) if h is not None else 0
    has_a = int(a.get("has_statcast_offense", 0)) if a is not None else 0
    return {
        "home_xwoba_roll": home_x,
        "away_xwoba_roll": away_x,
        "home_barrel_pct_roll": home_b,
        "away_barrel_pct_roll": away_b,
        "home_hard_hit_pct_roll": home_hh,
        "away_hard_hit_pct_roll": away_hh,
        "xwoba_off_diff": home_x - away_x,
        "has_statcast_offense": 1 if (has_h == 1 and has_a == 1) else 0,
    }


def _raw_predictions(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    home_x = pd.to_numeric(df.get("home_xwoba_roll", LEAGUE_XWOBA), errors="coerce").fillna(LEAGUE_XWOBA).to_numpy()
    away_x = pd.to_numeric(df.get("away_xwoba_roll", LEAGUE_XWOBA), errors="coerce").fillna(LEAGUE_XWOBA).to_numpy()
    home_b = pd.to_numeric(df.get("home_barrel_pct_roll", LEAGUE_BARREL_PCT), errors="coerce").fillna(LEAGUE_BARREL_PCT).to_numpy()
    away_b = pd.to_numeric(df.get("away_barrel_pct_roll", LEAGUE_BARREL_PCT), errors="coerce").fillna(LEAGUE_BARREL_PCT).to_numpy()
    on = pd.to_numeric(df.get("has_statcast_offense", 0), errors="coerce").fillna(0).to_numpy(dtype=float)
    xwoba_spread = home_x - away_x
    barrel_spread = home_b - away_b
    combined_xwoba = home_x + away_x - 2.0 * LEAGUE_XWOBA
    combined_barrel = home_b + away_b - 2.0 * LEAGUE_BARREL_PCT
    total = LEAGUE_TOTAL + on * (XWOBA_TO_TOTAL * combined_xwoba + BARREL_TO_TOTAL * combined_barrel)
    margin = on * (XWOBA_TO_MARGIN * xwoba_spread + BARREL_TO_MARGIN * barrel_spread)
    return total, margin


class StatcastOffenseMember(BaseballMemberModel):
    name = "statcast_offense"

    def __init__(self) -> None:
        self._total_bias = 0.0
        self._margin_bias = 0.0

    def fit(self, train_df: pd.DataFrame) -> None:
        mask = train_df.get("has_statcast_offense", pd.Series(0, index=train_df.index)) == 1
        if mask.sum() < 50:
            self._total_bias = 0.0
            self._margin_bias = 0.0
            return
        sub = train_df.loc[mask]
        raw_total, raw_margin = _raw_predictions(sub)
        self._total_bias = float(sub["total_final"].mean() - np.mean(raw_total))
        self._margin_bias = float(sub["margin_final"].mean() - np.mean(raw_margin))

    def predict(self, df: pd.DataFrame) -> MemberPrediction:
        raw_total, raw_margin = _raw_predictions(df)
        return MemberPrediction(
            member=self.name,
            total=raw_total + self._total_bias,
            margin=raw_margin + self._margin_bias,
        )
