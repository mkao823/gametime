"""Starting-pitcher ensemble member (W6h)."""
from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from gametime.ingest.mlb_pitchers import (
    LEAGUE_FIP,
    _PitcherCumStats,
    fetch_probable_pitchers,
    rebuild_cum_stats_from_sidecar,
)
from gametime.pregame.baseball.models.base import BaseballMemberModel
from gametime.pregame.baseball.prediction import MemberPrediction

PITCHER_FEATURE_COLUMNS = [
    "home_sp_fip",
    "away_sp_fip",
    "sp_fip_diff",
    "home_sp_rest_days",
    "away_sp_rest_days",
]

# v1 heuristic: runs per 1.0 FIP point (lower FIP = better = fewer runs)
FIP_TO_TOTAL = 0.18
FIP_TO_MARGIN = 0.22
LEAGUE_TOTAL = 8.7


def attach_pitcher(
    table: pd.DataFrame,
    pitcher_games: pd.DataFrame,
) -> pd.DataFrame:
    """Join pre-game SP features from pitcher sidecar; league-average fallback when missing."""
    out = table.copy()
    drop_cols = [
        c
        for c in (
            *PITCHER_FEATURE_COLUMNS,
            "has_starting_pitcher",
            "home_sp_id",
            "away_sp_id",
        )
        if c in out.columns
    ]
    if drop_cols:
        out = out.drop(columns=drop_cols)

    if pitcher_games.empty:
        for col in PITCHER_FEATURE_COLUMNS:
            if col == "sp_fip_diff":
                out[col] = 0.0
            elif "fip" in col:
                out[col] = LEAGUE_FIP
            else:
                out[col] = 5.0
        out["has_starting_pitcher"] = 0
        return out

    pg = pitcher_games[
        [
            "game_id",
            "home_sp_id",
            "away_sp_id",
            "home_sp_fip",
            "away_sp_fip",
            "home_sp_rest_days",
            "away_sp_rest_days",
            "has_starting_pitcher",
        ]
    ].drop_duplicates("game_id")
    out = out.merge(pg, on="game_id", how="left", suffixes=("", "_pg"))

    has = out["has_starting_pitcher"].fillna(0).astype(int)
    out["home_sp_fip"] = out["home_sp_fip"].fillna(LEAGUE_FIP)
    out["away_sp_fip"] = out["away_sp_fip"].fillna(LEAGUE_FIP)
    out["home_sp_rest_days"] = out["home_sp_rest_days"].fillna(5.0)
    out["away_sp_rest_days"] = out["away_sp_rest_days"].fillna(5.0)
    out["sp_fip_diff"] = out["home_sp_fip"] - out["away_sp_fip"]
    out["has_starting_pitcher"] = has
    return out


def _team_latest_sp_fip(
    pitcher_games: pd.DataFrame,
    games: pd.DataFrame,
    team: str,
) -> tuple[float, float]:
    """Last known starter FIP and rest for a team from sidecar (pregame fallback)."""
    if pitcher_games.empty or games.empty:
        return LEAGUE_FIP, 5.0
    merged = pitcher_games.merge(games[["game_id", "game_date", "home_team", "away_team"]], on="game_id")
    merged["game_date"] = pd.to_datetime(merged["game_date"])
    home_rows = merged[merged["home_team"] == team].sort_values("game_date")
    away_rows = merged[merged["away_team"] == team].sort_values("game_date")
    if not home_rows.empty:
        row = home_rows.iloc[-1]
        return float(row["home_sp_fip"]), float(row.get("home_sp_rest_days", 5.0))
    if not away_rows.empty:
        row = away_rows.iloc[-1]
        return float(row["away_sp_fip"]), float(row.get("away_sp_rest_days", 5.0))
    return LEAGUE_FIP, 5.0


def latest_pitcher_columns(
    *,
    home: str,
    away: str,
    games: pd.DataFrame,
    pitcher_games: pd.DataFrame,
    game_date: Optional[date] = None,
) -> dict[str, float]:
    """Inference row pitcher columns (probable SP + cumulative FIP when available)."""
    game_date = game_date or date.today()
    cum = rebuild_cum_stats_from_sidecar(pitcher_games, games)
    home_id, away_id = fetch_probable_pitchers(game_date, home, away)
    gd = pd.Timestamp(game_date).normalize()

    if home_id and away_id:
        home_fip = cum.get(int(home_id), _PitcherCumStats()).fip_prior()
        away_fip = cum.get(int(away_id), _PitcherCumStats()).fip_prior()
        home_rest = cum.get(int(home_id), _PitcherCumStats()).rest_days(gd)
        away_rest = cum.get(int(away_id), _PitcherCumStats()).rest_days(gd)
        has_sp = 1
    else:
        home_fip, home_rest = _team_latest_sp_fip(pitcher_games, games, home.upper())
        away_fip, away_rest = _team_latest_sp_fip(pitcher_games, games, away.upper())
        has_sp = 0

    return {
        "home_sp_fip": float(home_fip),
        "away_sp_fip": float(away_fip),
        "sp_fip_diff": float(home_fip - away_fip),
        "home_sp_rest_days": float(home_rest),
        "away_sp_rest_days": float(away_rest),
        "has_starting_pitcher": has_sp,
    }


class PitcherMember(BaseballMemberModel):
    """Map SP FIP differential to total and margin (v1 fixed heuristic)."""

    name = "pitcher"

    def __init__(self) -> None:
        self._total_bias = 0.0
        self._margin_bias = 0.0

    def fit(self, train_df: pd.DataFrame) -> None:
        """Optional bias calibration when pitcher signal is present on train."""
        mask = train_df.get("has_starting_pitcher", pd.Series(0, index=train_df.index)) == 1
        if mask.sum() < 50:
            self._total_bias = 0.0
            self._margin_bias = 0.0
            return
        sub = train_df.loc[mask]
        diff = sub["home_sp_fip"].to_numpy() - sub["away_sp_fip"].to_numpy()
        raw_total = LEAGUE_TOTAL + FIP_TO_TOTAL * diff
        raw_margin = -FIP_TO_MARGIN * diff
        self._total_bias = float(sub["total_final"].mean() - np.mean(raw_total))
        self._margin_bias = float(sub["margin_final"].mean() - np.mean(raw_margin))

    def predict(self, df: pd.DataFrame) -> MemberPrediction:
        diff = df["home_sp_fip"].to_numpy() - df["away_sp_fip"].to_numpy()
        total = LEAGUE_TOTAL + FIP_TO_TOTAL * diff + self._total_bias
        margin = -FIP_TO_MARGIN * diff + self._margin_bias
        return MemberPrediction(member=self.name, total=total, margin=margin)
