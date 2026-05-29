"""Park run-environment ensemble member (W6i)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from gametime.ingest.mlb_park import LEAGUE_PARK_FACTOR, build_shifted_park_factors
from gametime.pregame.baseball.models.base import BaseballMemberModel
from gametime.pregame.baseball.prediction import MemberPrediction

LEAGUE_TOTAL = 8.7
PARK_TO_MARGIN = 0.35


def attach_park(
    table: pd.DataFrame,
    games: pd.DataFrame,
    park_factors: pd.DataFrame | None = None,
) -> pd.DataFrame:
    out = table.copy()
    for col in ("home_park_factor", "park_factor_log", "has_park_factor"):
        if col in out.columns:
            out = out.drop(columns=[col])
    out = out.merge(build_shifted_park_factors(games), on="game_id", how="left")
    static = park_factors if park_factors is not None else pd.DataFrame()
    if not static.empty and "home_team" in out.columns:
        st = static[["home_team", "park_factor_runs"]].drop_duplicates("home_team")
        out = out.merge(st, on="home_team", how="left", suffixes=("", "_static"))
        missing = out["has_park_factor"].fillna(0).astype(int) == 0
        out.loc[missing, "home_park_factor"] = out.loc[missing, "park_factor_runs"].fillna(
            LEAGUE_PARK_FACTOR
        )
        static_ok = missing & out["park_factor_runs"].notna()
        out.loc[static_ok, "has_park_factor"] = 1
        out = out.drop(columns=["park_factor_runs"], errors="ignore")
    out["home_park_factor"] = out["home_park_factor"].fillna(LEAGUE_PARK_FACTOR)
    out["has_park_factor"] = out["has_park_factor"].fillna(0).astype(int)
    out["park_factor_log"] = np.log(out["home_park_factor"].clip(lower=0.5, upper=2.0))
    return out


def latest_park_columns(*, home: str, park_factors: pd.DataFrame) -> dict[str, float]:
    home = home.upper()
    if park_factors.empty:
        return {"home_park_factor": 1.0, "park_factor_log": 0.0, "has_park_factor": 0}
    row = park_factors.loc[park_factors["home_team"] == home]
    if row.empty or pd.isna(row.iloc[0].get("park_factor_runs")):
        return {"home_park_factor": 1.0, "park_factor_log": 0.0, "has_park_factor": 0}
    pf = float(row.iloc[0]["park_factor_runs"])
    return {
        "home_park_factor": pf,
        "park_factor_log": float(np.log(np.clip(pf, 0.5, 2.0))),
        "has_park_factor": 1,
    }


class ParkFactorMember(BaseballMemberModel):
    name = "park_factor"

    def __init__(self) -> None:
        self._total_bias = 0.0
        self._margin_bias = 0.0

    def fit(self, train_df: pd.DataFrame) -> None:
        mask = train_df.get("has_park_factor", pd.Series(0, index=train_df.index)) == 1
        if mask.sum() < 50:
            return
        sub = train_df.loc[mask]
        pf = sub["home_park_factor"].to_numpy()
        self._total_bias = float(sub["total_final"].mean() - np.mean(LEAGUE_TOTAL * pf))
        self._margin_bias = float(
            sub["margin_final"].mean() - np.mean(PARK_TO_MARGIN * (pf - 1.0))
        )

    def predict(self, df: pd.DataFrame) -> MemberPrediction:
        pf = df["home_park_factor"].to_numpy()
        return MemberPrediction(
            member=self.name,
            total=LEAGUE_TOTAL * pf + self._total_bias,
            margin=PARK_TO_MARGIN * (pf - 1.0) + self._margin_bias,
        )
