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
    # starting pitcher (M1 / W6h); league-average fallback when has_starting_pitcher=0
    "home_sp_fip",
    "away_sp_fip",
    "sp_fip_diff",
    "home_sp_rest_days",
    "away_sp_rest_days",
    # park run environment (M2 / W6i)
    "home_park_factor",
    "park_factor_log",
    "has_park_factor",
    # weather sidecar (M3 / W6j)
    "temp_f",
    "wind_mph",
    "humidity_pct",
    "is_dome",
    "has_weather",
    # reserved for future ingest
    "has_lineup",
    "has_starting_pitcher",
]

LEAGUE_FIP = 4.20

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
    for col, default in (
        ("temp_f", 70.0),
        ("wind_mph", 0.0),
        ("humidity_pct", 50.0),
        ("is_dome", 0),
        ("has_weather", 0),
    ):
        if col not in table.columns:
            table[col] = default
    table["has_lineup"] = 0
    for col in ("home_sp_fip", "away_sp_fip", "sp_fip_diff", "home_sp_rest_days", "away_sp_rest_days"):
        if col not in table.columns:
            if col == "sp_fip_diff":
                table[col] = 0.0
            elif "fip" in col:
                table[col] = LEAGUE_FIP
            else:
                table[col] = 5.0
    if "has_starting_pitcher" not in table.columns:
        table["has_starting_pitcher"] = 0
    for col, default in (
        ("home_park_factor", 1.0),
        ("park_factor_log", 0.0),
        ("has_park_factor", 0),
    ):
        if col not in table.columns:
            table[col] = default
    table = table.dropna(subset=FEATURE_COLUMNS[:8])
    return table


def _latest_runs_strength(
    games: pd.DataFrame,
    *,
    home: str,
    away: str,
    window: int,
) -> dict[str, float]:
    """Per-team runs-strength rates from prior games only (for live inference)."""
    games = games.sort_values("game_date").reset_index(drop=True)
    tg = _team_game_rows(games)
    g = tg.groupby("team", sort=False)
    min_periods = max(3, window // 6)
    tg = tg.copy()
    tg["rs_off"] = g["runs_for"].transform(
        lambda s: s.shift(1).rolling(window, min_periods=min_periods).mean()
    )
    tg["rs_def"] = g["runs_against"].transform(
        lambda s: s.shift(1).rolling(window, min_periods=min_periods).mean()
    )

    def _last(team: str, col: str) -> float:
        sub = tg.loc[tg["team"] == team, col]
        if sub.empty or pd.isna(sub.iloc[-1]):
            return LEAGUE_RPG
        return float(sub.iloc[-1])

    return {
        "home_rs_off": _last(home, "rs_off"),
        "home_rs_def": _last(home, "rs_def"),
        "away_rs_off": _last(away, "rs_off"),
        "away_rs_def": _last(away, "rs_def"),
    }


def _form_game_count(tg: pd.DataFrame, team: str, window: int) -> int:
    sub = tg.loc[tg["team"] == team, "runs_for"]
    if sub.empty:
        return 0
    prior = sub.shift(1).tail(window)
    return int(prior.notna().sum())


def build_inference_row(
    *,
    home: str,
    away: str,
    games: pd.DataFrame,
    form_window: int = 10,
    runs_strength_window: int = 30,
    is_playoff: bool = False,
) -> pd.DataFrame:
    """One-row feature frame for a hypothetical matchup (no label leakage)."""
    home, away = home.upper(), away.upper()
    games = games.sort_values("game_date").reset_index(drop=True)
    tg = _rolling_team_stats(_team_game_rows(games), form_window)

    def _latest(team: str) -> pd.Series:
        sub = tg.loc[tg["team"] == team]
        if sub.empty:
            raise ValueError(f"No historical games for team {team!r}")
        return sub.iloc[-1]

    h = _latest(home)
    a = _latest(away)
    rs = _latest_runs_strength(
        games, home=home, away=away, window=runs_strength_window
    )

    row = {
        "home_form_runs_scored": float(h["form_runs_scored"])
        if pd.notna(h["form_runs_scored"])
        else LEAGUE_RPG,
        "home_form_runs_allowed": float(h["form_runs_allowed"])
        if pd.notna(h["form_runs_allowed"])
        else LEAGUE_RPG,
        "away_form_runs_scored": float(a["form_runs_scored"])
        if pd.notna(a["form_runs_scored"])
        else LEAGUE_RPG,
        "away_form_runs_allowed": float(a["form_runs_allowed"])
        if pd.notna(a["form_runs_allowed"])
        else LEAGUE_RPG,
        "home_form_winpct": float(h["form_winpct"]) if pd.notna(h["form_winpct"]) else 0.5,
        "away_form_winpct": float(a["form_winpct"]) if pd.notna(a["form_winpct"]) else 0.5,
        "home_rest_days": float(h["rest_days"]) if pd.notna(h["rest_days"]) else 1.0,
        "away_rest_days": float(a["rest_days"]) if pd.notna(a["rest_days"]) else 1.0,
        "home_win_streak": float(h["win_streak"]),
        "away_win_streak": float(a["win_streak"]),
        "is_playoff": int(bool(is_playoff)),
        "temp_f": 70.0,
        "wind_mph": 0.0,
        "humidity_pct": 50.0,
        "is_dome": 0,
        "has_weather": 0,
        "has_lineup": 0,
        "home_sp_fip": LEAGUE_FIP,
        "away_sp_fip": LEAGUE_FIP,
        "sp_fip_diff": 0.0,
        "home_sp_rest_days": 5.0,
        "away_sp_rest_days": 5.0,
        "has_starting_pitcher": 0,
        "home_park_factor": 1.0,
        "park_factor_log": 0.0,
        "has_park_factor": 0,
        **rs,
    }
    row["form_off_diff"] = row["home_form_runs_scored"] - row["away_form_runs_scored"]
    row["form_def_diff"] = (
        row["away_form_runs_allowed"] - row["home_form_runs_allowed"]
    )
    row["expected_form_total"] = (
        row["home_form_runs_scored"] + row["away_form_runs_scored"]
    )
    return pd.DataFrame([row])
