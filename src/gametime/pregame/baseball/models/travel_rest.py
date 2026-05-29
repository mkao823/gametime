"""Travel / schedule stress member (W6n): fatigue from games.parquet only."""
from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from gametime.pregame.baseball.features import _team_game_rows
from gametime.pregame.baseball.models.base import BaseballMemberModel
from gametime.pregame.baseball.prediction import MemberPrediction

_TEAM_TZ_OFFSET: dict[str, float] = {
    "ARI": -7, "ATL": -5, "BAL": -5, "BOS": -5, "CHC": -6, "CHW": -6,
    "CIN": -5, "CLE": -5, "COL": -7, "DET": -5, "HOU": -6, "KCR": -6,
    "LAA": -8, "LAD": -8, "MIA": -5, "MIL": -6, "MIN": -6, "NYM": -5,
    "NYY": -5, "OAK": -8, "PHI": -5, "PIT": -5, "SDP": -8, "SEA": -8,
    "SFG": -8, "STL": -6, "TBR": -5, "TEX": -6, "TOR": -5, "WSN": -5,
    "ATH": -8, "AZ": -7, "TB": -5, "KC": -6, "SF": -8, "SD": -8,
    "LA": -8, "CWS": -6, "WAS": -5,
}

LEAGUE_TOTAL = 8.7
DEFAULT_GAMES_3D = 0.0
DEFAULT_STREAK = 0.0


def _venue_tz(team: str, opp: str, is_home: float) -> float:
    venue_team = team if is_home >= 0.5 else opp
    return _TEAM_TZ_OFFSET.get(str(venue_team).upper(), -6.0)


def _games_in_last_n_days(dates: pd.Series, n: int = 3) -> pd.Series:
    dt = pd.to_datetime(dates)
    out = np.zeros(len(dt), dtype=float)
    vals = dt.values
    for i in range(1, len(vals)):
        cur = vals[i]
        cutoff = cur - np.timedelta64(n, "D")
        prior = vals[:i]
        out[i] = float(np.sum((prior >= cutoff) & (prior < cur)))
    return pd.Series(out, index=dates.index)


def _consecutive_home_streak(is_home: pd.Series) -> pd.Series:
    streak: list[float] = []
    cur = 0
    for h in is_home.shift(1):
        if pd.isna(h):
            streak.append(0.0)
            cur = 0
        elif float(h) >= 0.5:
            cur += 1
            streak.append(float(cur))
        else:
            cur = 0
            streak.append(0.0)
    return pd.Series(streak, index=is_home.index)


def _consecutive_road_streak(is_home: pd.Series) -> pd.Series:
    streak: list[float] = []
    cur = 0
    for h in is_home.shift(1):
        if pd.isna(h):
            streak.append(0.0)
            cur = 0
        elif float(h) < 0.5:
            cur += 1
            streak.append(float(cur))
        else:
            cur = 0
            streak.append(0.0)
    return pd.Series(streak, index=is_home.index)


def _tz_shift_series(tg: pd.DataFrame) -> pd.Series:
    out = pd.Series(0.0, index=tg.index, dtype=float)
    for team, idx in tg.groupby("team", sort=False).groups.items():
        sub = tg.loc[idx].sort_values("game_date")
        prev_tz: float | None = None
        for row_idx, row in sub.iterrows():
            tz = _venue_tz(str(team), row["opp"], float(row["is_home"]))
            if prev_tz is not None:
                out.at[row_idx] = abs(tz - prev_tz)
            prev_tz = tz
    return out


def _doubleheader_by_game_id(games: pd.DataFrame) -> pd.Series:
    g = games.copy()
    g["game_date"] = pd.to_datetime(g["game_date"])
    home_cnt = g.groupby(["home_team", "game_date"])["game_id"].transform("count")
    away_cnt = g.groupby(["away_team", "game_date"])["game_id"].transform("count")
    flags = ((home_cnt > 1) | (away_cnt > 1)).astype(int)
    return pd.Series(flags.values, index=g["game_id"])


def attach_travel_rest(table: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    games = games.sort_values("game_date").reset_index(drop=True)
    tg = _team_game_rows(games)
    g = tg.groupby("team", sort=False)
    tg = tg.copy()
    tg["games_last_3d"] = g["game_date"].transform(lambda s: _games_in_last_n_days(s, 3))
    tg["consecutive_home"] = g["is_home"].transform(_consecutive_home_streak)
    tg["consecutive_road"] = g["is_home"].transform(_consecutive_road_streak)
    tg["tz_shift_hours"] = _tz_shift_series(tg)

    home_ctx = tg[tg["is_home"] == 1].set_index("game_id")
    away_ctx = tg[tg["is_home"] == 0].set_index("game_id")
    dh = _doubleheader_by_game_id(games)

    out = table.copy()
    out["home_games_last_3d"] = out["game_id"].map(home_ctx["games_last_3d"])
    out["away_games_last_3d"] = out["game_id"].map(away_ctx["games_last_3d"])
    out["home_consecutive_home"] = out["game_id"].map(home_ctx["consecutive_home"])
    out["away_consecutive_road"] = out["game_id"].map(away_ctx["consecutive_road"])
    out["away_tz_shift_hours"] = out["game_id"].map(away_ctx["tz_shift_hours"])
    out["is_doubleheader"] = out["game_id"].map(dh).fillna(0).astype(int)

    for col, default in (
        ("home_games_last_3d", DEFAULT_GAMES_3D),
        ("away_games_last_3d", DEFAULT_GAMES_3D),
        ("home_consecutive_home", DEFAULT_STREAK),
        ("away_consecutive_road", DEFAULT_STREAK),
        ("away_tz_shift_hours", 0.0),
    ):
        out[col] = out[col].fillna(default)

    home_rest = pd.to_numeric(out.get("home_rest_days", 1.0), errors="coerce").fillna(1.0)
    away_rest = pd.to_numeric(out.get("away_rest_days", 1.0), errors="coerce").fillna(1.0)
    home_fatigue = out["home_games_last_3d"] + 0.35 * out["home_consecutive_home"] + np.maximum(0.0, 3.0 - home_rest)
    away_fatigue = out["away_games_last_3d"] + 0.35 * out["away_consecutive_road"] + 0.15 * out["away_tz_shift_hours"] + np.maximum(0.0, 3.0 - away_rest)
    out["schedule_fatigue_diff"] = away_fatigue - home_fatigue
    return out


def _team_games_last_3d(team_games: pd.DataFrame, as_of: pd.Timestamp) -> float:
    prior = team_games[pd.to_datetime(team_games["game_date"]) < as_of]
    if prior.empty:
        return DEFAULT_GAMES_3D
    cutoff = as_of - pd.Timedelta(days=3)
    dates = pd.to_datetime(prior["game_date"])
    return float(((dates >= cutoff) & (dates < as_of)).sum())


def _streak_entering_home(team_games: pd.DataFrame) -> float:
    if team_games.empty:
        return DEFAULT_STREAK
    streak = 0
    for h in team_games["is_home"].iloc[::-1]:
        if float(h) >= 0.5:
            streak += 1
        else:
            break
    return float(streak)


def _streak_entering_road(team_games: pd.DataFrame) -> float:
    if team_games.empty:
        return DEFAULT_STREAK
    streak = 0
    for h in team_games["is_home"].iloc[::-1]:
        if float(h) < 0.5:
            streak += 1
        else:
            break
    return float(streak)


def _away_tz_shift_entering(team_games: pd.DataFrame, *, home: str, away: str) -> float:
    if team_games.empty:
        return 0.0
    last = team_games.iloc[-1]
    prev_tz = _venue_tz(last["team"], last["opp"], float(last["is_home"]))
    return abs(_venue_tz(away, home, 0.0) - prev_tz)


def latest_schedule_columns(*, home: str, away: str, games: pd.DataFrame, game_date: Optional[date] = None) -> dict[str, float]:
    home, away = home.upper(), away.upper()
    if games.empty:
        return {"home_games_last_3d": 0.0, "away_games_last_3d": 0.0, "home_consecutive_home": 0.0,
                "away_consecutive_road": 0.0, "is_doubleheader": 0, "away_tz_shift_hours": 0.0,
                "schedule_fatigue_diff": 0.0}
    games = games.sort_values("game_date").reset_index(drop=True)
    tg = _team_game_rows(games)
    as_of = pd.Timestamp(game_date) if game_date else pd.to_datetime(tg["game_date"]).max() + pd.Timedelta(days=1)
    home_tg = tg[tg["team"] == home].sort_values("game_date")
    away_tg = tg[tg["team"] == away].sort_values("game_date")
    home_rest = away_rest = 1.0
    if not home_tg.empty:
        home_rest = float(max(0, (as_of - pd.to_datetime(home_tg.iloc[-1]["game_date"])).days - 1))
    if not away_tg.empty:
        away_rest = float(max(0, (as_of - pd.to_datetime(away_tg.iloc[-1]["game_date"])).days - 1))
    home_g3 = _team_games_last_3d(home_tg, as_of)
    away_g3 = _team_games_last_3d(away_tg, as_of)
    home_streak = _streak_entering_home(home_tg)
    away_road = _streak_entering_road(away_tg)
    away_tz = _away_tz_shift_entering(away_tg, home=home, away=away)
    home_fatigue = home_g3 + 0.35 * home_streak + max(0.0, 3.0 - home_rest)
    away_fatigue = away_g3 + 0.35 * away_road + 0.15 * away_tz + max(0.0, 3.0 - away_rest)
    return {
        "home_games_last_3d": home_g3, "away_games_last_3d": away_g3,
        "home_consecutive_home": home_streak, "away_consecutive_road": away_road,
        "is_doubleheader": 0, "away_tz_shift_hours": away_tz,
        "schedule_fatigue_diff": away_fatigue - home_fatigue,
        "home_rest_days": home_rest, "away_rest_days": away_rest,
    }


def _raw_predictions(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    fatigue = df["schedule_fatigue_diff"].to_numpy()
    dh = df["is_doubleheader"].to_numpy(dtype=float)
    games3 = df["home_games_last_3d"].to_numpy() + df["away_games_last_3d"].to_numpy()
    home_rest = pd.to_numeric(df["home_rest_days"], errors="coerce").fillna(1.0).to_numpy()
    away_rest = pd.to_numeric(df["away_rest_days"], errors="coerce").fillna(1.0).to_numpy()
    raw_margin = 0.12 * fatigue - 0.04 * (home_rest - away_rest)
    raw_total = LEAGUE_TOTAL - 0.08 * games3 + 0.25 * dh
    return raw_total, raw_margin


class TravelRestMember(BaseballMemberModel):
    name = "travel_rest"

    def __init__(self) -> None:
        self._total_bias = 0.0
        self._margin_bias = 0.0

    def fit(self, train_df: pd.DataFrame) -> None:
        raw_total, raw_margin = _raw_predictions(train_df)
        self._total_bias = float(train_df["total_final"].mean() - np.mean(raw_total))
        self._margin_bias = float(train_df["margin_final"].mean() - np.mean(raw_margin))

    def predict(self, df: pd.DataFrame) -> MemberPrediction:
        raw_total, raw_margin = _raw_predictions(df)
        return MemberPrediction(member=self.name, total=raw_total + self._total_bias, margin=raw_margin + self._margin_bias)
