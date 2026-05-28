"""MLB pregame features: rolling team form + placeholders for future context.

FEATURE_ROADMAP (not yet wired):
  - starting_pitcher SPxRA/FIP, bullpen fatigue
  - lineup wOBA / platoon splits
  - park factor, roof/dome
  - weather (temp, wind, humidity via open meteo or retrosheet)
"""
from __future__ import annotations

import pandas as pd

LEAGUE_RPG = 4.5

FEATURE_COLUMNS = [
    "home_form_runs_scored",
    "home_form_runs_allowed",
    "away_form_runs_scored",
    "away_form_runs_allowed",
    "form_off_diff",
    "form_def_diff",
    "expected_form_total",
    "home_form_winpct",
    "away_form_winpct",
    "home_rest_days",
    "away_rest_days",
    "home_win_streak",
    "away_win_streak",
    "is_playoff",
    # reserved for future ingest (0 until populated)
    "has_weather",
    "has_lineup",
    "has_starting_pitcher",
]

TARGET_TOTAL = "total_final"
TARGET_MARGIN = "margin_final"
TARGET_WINNER = "home_win"


def _team_game_rows(games: pd.DataFrame) -> pd.DataFrame:
    home = games.assign(
        team=games["home_team"],
        opp=games["away_team"],
        runs_for=games["home_runs"],
        runs_against=games["away_runs"],
        is_home=1,
        won=(games["margin_final"] > 0).astype(int),
    )
    away = games.assign(
        team=games["away_team"],
        opp=games["home_team"],
        runs_for=games["away_runs"],
        runs_against=games["home_runs"],
        is_home=0,
        won=(games["margin_final"] < 0).astype(int),
    )
    cols = [
        "game_id",
        "game_date",
        "team",
        "opp",
        "runs_for",
        "runs_against",
        "is_home",
        "won",
        "season_start_year",
        "seasontype",
    ]
    return pd.concat([home[cols], away[cols]], ignore_index=True).sort_values(
        ["team", "game_date"]
    )


def _rolling_team_stats(tg: pd.DataFrame, window: int) -> pd.DataFrame:
    g = tg.groupby("team", sort=False)
    out = tg.copy()
    out["form_runs_scored"] = g["runs_for"].transform(
        lambda s: s.shift(1).rolling(window, min_periods=3).mean()
    )
    out["form_runs_allowed"] = g["runs_against"].transform(
        lambda s: s.shift(1).rolling(window, min_periods=3).mean()
    )
    out["form_winpct"] = g["won"].transform(
        lambda s: s.shift(1).rolling(window, min_periods=3).mean()
    )
    out["rest_days"] = g["game_date"].diff().dt.days
    out["win_streak"] = g["won"].transform(_win_streak)
    return out


def _win_streak(won: pd.Series) -> pd.Series:
    streak = []
    cur = 0
    for w in won.shift(1).fillna(0):
        if w >= 0.5:
            cur = cur + 1 if cur >= 0 else 1
        else:
            cur = cur - 1 if cur <= 0 else -1
        streak.append(float(cur))
    return pd.Series(streak, index=won.index)


def build_training_table(games: pd.DataFrame, *, form_window: int = 10) -> pd.DataFrame:
    games = games.sort_values("game_date").reset_index(drop=True)
    games["home_win"] = (games["margin_final"] > 0).astype(int)
    tg = _rolling_team_stats(_team_game_rows(games), form_window)

    home_ctx = tg[tg["is_home"] == 1].set_index("game_id")
    away_ctx = tg[tg["is_home"] == 0].set_index("game_id")

    table = games.copy()
    table["home_form_runs_scored"] = table["game_id"].map(home_ctx["form_runs_scored"])
    table["home_form_runs_allowed"] = table["game_id"].map(home_ctx["form_runs_allowed"])
    table["away_form_runs_scored"] = table["game_id"].map(away_ctx["form_runs_scored"])
    table["away_form_runs_allowed"] = table["game_id"].map(away_ctx["form_runs_allowed"])
    table["home_form_winpct"] = table["game_id"].map(home_ctx["form_winpct"])
    table["away_form_winpct"] = table["game_id"].map(away_ctx["form_winpct"])
    table["home_rest_days"] = table["game_id"].map(home_ctx["rest_days"])
    table["away_rest_days"] = table["game_id"].map(away_ctx["rest_days"])
    table["home_win_streak"] = table["game_id"].map(home_ctx["win_streak"])
    table["away_win_streak"] = table["game_id"].map(away_ctx["win_streak"])

    for col in (
        "home_form_runs_scored",
        "home_form_runs_allowed",
        "away_form_runs_scored",
        "away_form_runs_allowed",
        "home_form_winpct",
        "away_form_winpct",
    ):
        if "scored" in col or "allowed" in col:
            table[col] = table[col].fillna(LEAGUE_RPG)
        else:
            table[col] = table[col].fillna(0.5)

    table["form_off_diff"] = table["home_form_runs_scored"] - table["away_form_runs_scored"]
    table["form_def_diff"] = table["away_form_runs_allowed"] - table["home_form_runs_allowed"]
    table["expected_form_total"] = (
        table["home_form_runs_scored"] + table["away_form_runs_scored"]
    )
    table["is_playoff"] = (table["seasontype"] == "po").astype(int)
    table["has_weather"] = 0
    table["has_lineup"] = 0
    table["has_starting_pitcher"] = 0
    table = table.dropna(subset=FEATURE_COLUMNS[:8])
    return table
