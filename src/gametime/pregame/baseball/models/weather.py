"""Weather feature attach + ensemble member (W6j)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from gametime.pregame.baseball.models.base import BaseballMemberModel
from gametime.pregame.baseball.prediction import MemberPrediction

LEAGUE_TOTAL = 8.7
TEMP_REF_F = 70.0
HUMIDITY_REF = 50.0


def attach_weather(table: pd.DataFrame, weather_games: pd.DataFrame) -> pd.DataFrame:
    out = table.copy()
    drop_cols = ["temp_f", "wind_mph", "humidity_pct", "is_dome", "has_weather"]
    out = out.drop(columns=[c for c in drop_cols if c in out.columns], errors="ignore")
    wg = weather_games.copy() if weather_games is not None else pd.DataFrame()
    if not wg.empty:
        cols = [c for c in ("game_id", "temp_f", "wind_mph", "humidity_pct", "is_dome", "has_weather") if c in wg.columns]
        out = out.merge(wg[cols], on="game_id", how="left")

    def _col(name: str, default: float | int) -> pd.Series:
        if name in out.columns:
            return pd.to_numeric(out[name], errors="coerce")
        return pd.Series(default, index=out.index, dtype=float)

    out["temp_f"] = _col("temp_f", 70.0).fillna(70.0)
    out["wind_mph"] = _col("wind_mph", 0.0).fillna(0.0)
    out["humidity_pct"] = _col("humidity_pct", 50.0).fillna(50.0)
    out["is_dome"] = _col("is_dome", 0).fillna(0).astype(int)
    out.loc[out["is_dome"] == 1, "wind_mph"] = 0.0
    out["has_weather"] = _col("has_weather", 0).fillna(0).astype(int)
    return out


def latest_weather_columns(*, home: str, weather_games: pd.DataFrame) -> dict[str, float]:
    if weather_games is None or weather_games.empty:
        return {
            "temp_f": 70.0,
            "wind_mph": 0.0,
            "humidity_pct": 50.0,
            "is_dome": 0,
            "has_weather": 0,
        }
    sub = weather_games.loc[
        weather_games["home_team"].astype(str).str.upper() == home.upper()
    ].copy()
    if sub.empty:
        return {
            "temp_f": 70.0,
            "wind_mph": 0.0,
            "humidity_pct": 50.0,
            "is_dome": 0,
            "has_weather": 0,
        }
    sub["game_date"] = pd.to_datetime(sub["game_date"], errors="coerce")
    sub = sub.sort_values("game_date")
    row = sub.iloc[-1]
    return {
        "temp_f": float(row.get("temp_f", 70.0)),
        "wind_mph": 0.0 if int(row.get("is_dome", 0)) == 1 else float(row.get("wind_mph", 0.0)),
        "humidity_pct": float(row.get("humidity_pct", 50.0)),
        "is_dome": int(row.get("is_dome", 0)),
        "has_weather": int(row.get("has_weather", 0)),
    }


def _raw_predictions(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    temp = pd.to_numeric(df.get("temp_f", 70.0), errors="coerce").fillna(70.0).to_numpy()
    wind = pd.to_numeric(df.get("wind_mph", 0.0), errors="coerce").fillna(0.0).to_numpy()
    humidity = pd.to_numeric(df.get("humidity_pct", 50.0), errors="coerce").fillna(50.0).to_numpy()
    dome = pd.to_numeric(df.get("is_dome", 0), errors="coerce").fillna(0).to_numpy(dtype=float)
    weather_on = pd.to_numeric(df.get("has_weather", 0), errors="coerce").fillna(0).to_numpy(dtype=float)
    wind = np.where(dome >= 0.5, 0.0, wind)
    total_delta = 0.06 * (temp - TEMP_REF_F) + 0.04 * wind - 0.01 * (humidity - HUMIDITY_REF)
    total = LEAGUE_TOTAL + weather_on * total_delta
    margin = 0.02 * weather_on * np.clip(wind, 0.0, 25.0)
    return total, margin


class WeatherMember(BaseballMemberModel):
    name = "weather"

    def __init__(self) -> None:
        self._total_bias = 0.0
        self._margin_bias = 0.0

    def fit(self, train_df: pd.DataFrame) -> None:
        raw_total, raw_margin = _raw_predictions(train_df)
        self._total_bias = float(train_df["total_final"].mean() - np.mean(raw_total))
        self._margin_bias = float(train_df["margin_final"].mean() - np.mean(raw_margin))

    def predict(self, df: pd.DataFrame) -> MemberPrediction:
        raw_total, raw_margin = _raw_predictions(df)
        return MemberPrediction(
            member=self.name,
            total=raw_total + self._total_bias,
            margin=raw_margin + self._margin_bias,
        )
