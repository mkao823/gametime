"""Lineup strength attach + ensemble member (W6k)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from gametime.ingest.mlb_lineup import LEAGUE_WOBA, LINEUP_COLUMNS
from gametime.pregame.baseball.models.base import BaseballMemberModel
from gametime.pregame.baseball.prediction import MemberPrediction

LEAGUE_TOTAL = 8.7
WOBA_TO_TOTAL = 12.0
WOBA_TO_MARGIN = 8.0


def attach_lineup(table: pd.DataFrame, lineup_games: pd.DataFrame) -> pd.DataFrame:
    out = table.copy()
    drop_cols = [
        "home_lineup_woba",
        "away_lineup_woba",
        "lineup_platoon_diff",
        "has_lineup",
    ]
    out = out.drop(columns=[c for c in drop_cols if c in out.columns], errors="ignore")

    lg = lineup_games.copy() if lineup_games is not None else pd.DataFrame()
    if not lg.empty:
        cols = [c for c in LINEUP_COLUMNS if c in lg.columns]
        out = out.merge(lg[cols], on="game_id", how="left")

    for col, default in (
        ("home_lineup_woba", LEAGUE_WOBA),
        ("away_lineup_woba", LEAGUE_WOBA),
        ("lineup_platoon_diff", 0.0),
        ("has_lineup", 0),
    ):
        if col not in out.columns:
            out[col] = default
        else:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(default)

    out["has_lineup"] = out["has_lineup"].fillna(0).astype(int)
    return out


def _team_latest_lineup_woba(
    lineup_games: pd.DataFrame,
    games: pd.DataFrame,
    team: str,
) -> tuple[float, float, int]:
    if lineup_games.empty or games.empty:
        return LEAGUE_WOBA, LEAGUE_WOBA, 0
    merged = lineup_games.merge(
        games[["game_id", "game_date", "home_team", "away_team"]], on="game_id"
    )
    merged["game_date"] = pd.to_datetime(merged["game_date"])
    home_rows = merged[merged["home_team"] == team.upper()].sort_values("game_date")
    away_rows = merged[merged["away_team"] == team.upper()].sort_values("game_date")
    if not home_rows.empty:
        row = home_rows.iloc[-1]
        return (
            float(row["home_lineup_woba"]),
            float(row.get("lineup_platoon_diff", 0.0)),
            int(row.get("has_lineup", 0)),
        )
    if not away_rows.empty:
        row = away_rows.iloc[-1]
        return (
            float(row["away_lineup_woba"]),
            float(-row.get("lineup_platoon_diff", 0.0)),
            int(row.get("has_lineup", 0)),
        )
    return LEAGUE_WOBA, LEAGUE_WOBA, 0


def latest_lineup_columns(
    *,
    home: str,
    away: str,
    games: pd.DataFrame,
    lineup_games: pd.DataFrame,
) -> dict[str, float | int]:
    home_w, _, home_has = _team_latest_lineup_woba(lineup_games, games, home.upper())
    away_w, _, away_has = _team_latest_lineup_woba(lineup_games, games, away.upper())
    has_lineup = 1 if (home_has == 1 and away_has == 1) else 0
    return {
        "home_lineup_woba": home_w,
        "away_lineup_woba": away_w,
        "lineup_platoon_diff": home_w - away_w,
        "has_lineup": has_lineup,
    }


def _raw_predictions(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    home = pd.to_numeric(df.get("home_lineup_woba", LEAGUE_WOBA), errors="coerce").fillna(
        LEAGUE_WOBA
    ).to_numpy()
    away = pd.to_numeric(df.get("away_lineup_woba", LEAGUE_WOBA), errors="coerce").fillna(
        LEAGUE_WOBA
    ).to_numpy()
    platoon = pd.to_numeric(
        df.get("lineup_platoon_diff", home - away), errors="coerce"
    ).fillna(0.0).to_numpy()
    lineup_on = pd.to_numeric(df.get("has_lineup", 0), errors="coerce").fillna(0).to_numpy(
        dtype=float
    )
    combined_woba = home + away - 2.0 * LEAGUE_WOBA
    total = LEAGUE_TOTAL + lineup_on * WOBA_TO_TOTAL * combined_woba
    margin = lineup_on * WOBA_TO_MARGIN * platoon
    return total, margin


class LineupMember(BaseballMemberModel):
    name = "lineup"

    def __init__(self) -> None:
        self._total_bias = 0.0
        self._margin_bias = 0.0

    def fit(self, train_df: pd.DataFrame) -> None:
        mask = train_df.get("has_lineup", pd.Series(0, index=train_df.index)) == 1
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
