"""Pre-game feature assembly.

Training rows combine Elo, off/def Elo, rolling team context, and targets.
Live inference uses the same columns via build_inference_row().
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from gametime.pregame.team_context import (
    LEAGUE_PPG,
    current_h2h,
    current_team_context,
    enrich_games,
)

FEATURE_COLUMNS = [
    # strength
    "elo_home",
    "elo_away",
    "elo_diff",
    "home_off_elo",
    "away_off_elo",
    "home_def_elo",
    "away_def_elo",
    "off_elo_diff",
    "def_elo_diff",
    "elo_diff_x_playoff",
    # scoring form
    "home_form_margin",
    "home_form_total",
    "home_form_winpct",
    "away_form_margin",
    "away_form_total",
    "away_form_winpct",
    "home_form_off",
    "away_form_off",
    "home_form_def",
    "away_form_def",
    "form_off_diff",
    "expected_form_total",
    "home_form_total_std",
    "away_form_total_std",
    "home_form_margin_std",
    "away_form_margin_std",
    "form_def_diff",
    "home_form_q4_pace",
    "away_form_q4_pace",
    "form_q4_pace_diff",
    "expected_q4_pace",
    # momentum / schedule
    "home_win_streak",
    "away_win_streak",
    "home_rest_days",
    "away_rest_days",
    "home_is_back_to_back",
    "away_is_back_to_back",
    "home_po_game_n",
    "away_po_game_n",
    "series_game_n",
    # matchup history
    "h2h_avg_total",
    "h2h_home_margin",
    "is_playoff",
    # PO / series interactions
    "series_x_elo_diff",
    "series_x_form_margin",
    "home_po_x_elo",
    "away_po_x_elo",
]

from gametime.pregame.constants import (
    DEFAULT_BLOWOUT_MARGIN_PTS,
    TARGET_BLOWOUT,
    TARGET_MARGIN,
    TARGET_TOTAL,
)

_CONTEXT_DEFAULTS = {
    "home_form_off": LEAGUE_PPG,
    "away_form_off": LEAGUE_PPG,
    "home_form_def": LEAGUE_PPG,
    "away_form_def": LEAGUE_PPG,
    "form_off_diff": 0.0,
    "expected_form_total": 2.0 * LEAGUE_PPG,
    "home_form_total_std": 0.0,
    "away_form_total_std": 0.0,
    "home_form_margin_std": 0.0,
    "away_form_margin_std": 0.0,
    "form_def_diff": 0.0,
    "home_form_q4_pace": 220.0,
    "away_form_q4_pace": 220.0,
    "form_q4_pace_diff": 0.0,
    "expected_q4_pace": 220.0,
    "home_rest_days": 3.0,
    "away_rest_days": 3.0,
    "home_is_back_to_back": 0.0,
    "away_is_back_to_back": 0.0,
    "home_win_streak": 0.0,
    "away_win_streak": 0.0,
    "home_po_game_n": 0.0,
    "away_po_game_n": 0.0,
    "series_game_n": 0.0,
    "h2h_avg_total": 2.0 * LEAGUE_PPG,
    "h2h_home_margin": 0.0,
    "home_off_elo": 1500.0,
    "away_off_elo": 1500.0,
    "home_def_elo": 1500.0,
    "away_def_elo": 1500.0,
    "off_elo_diff": 0.0,
    "def_elo_diff": 0.0,
    "elo_diff_x_playoff": 0.0,
    "series_x_elo_diff": 0.0,
    "series_x_form_margin": 0.0,
    "home_po_x_elo": 0.0,
    "away_po_x_elo": 0.0,
}


def add_po_interaction_features(row: pd.Series) -> pd.Series:
    """PO/series interaction terms (same formula train + live)."""
    out = row.copy()
    elo_diff = float(out["elo_diff"])
    form_margin_diff = float(out["home_form_margin"]) - float(out["away_form_margin"])
    series_n = float(out.get("series_game_n", 0.0))
    is_po = float(out.get("is_playoff", 0.0))
    out["series_x_elo_diff"] = series_n * elo_diff / 100.0
    out["series_x_form_margin"] = series_n * form_margin_diff
    out["home_po_x_elo"] = float(out.get("home_po_game_n", 0.0)) * elo_diff / 100.0 * is_po
    out["away_po_x_elo"] = float(out.get("away_po_game_n", 0.0)) * (-elo_diff) / 100.0 * is_po
    return out


def add_po_interaction_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorized PO/series interactions for training tables."""
    out = df.copy()
    form_margin_diff = out["home_form_margin"] - out["away_form_margin"]
    series_n = out["series_game_n"].astype(float)
    is_po = out["is_playoff"].astype(float)
    out["series_x_elo_diff"] = series_n * out["elo_diff"] / 100.0
    out["series_x_form_margin"] = series_n * form_margin_diff
    out["home_po_x_elo"] = out["home_po_game_n"].astype(float) * out["elo_diff"] / 100.0 * is_po
    out["away_po_x_elo"] = out["away_po_game_n"].astype(float) * (-out["elo_diff"]) / 100.0 * is_po
    return out


def _league_default(window: int) -> dict[str, float]:
    return {
        "form_margin": 0.0,
        "form_total": 2.0 * LEAGUE_PPG,
        "form_winpct": 0.5,
        "n_games": 0.0,
    }


def _rolling_form_table(team_games: pd.DataFrame, window: int = 10) -> pd.DataFrame:
    tg = team_games.sort_values(["team", "game_id"]).reset_index(drop=True).copy()

    def _shifted_rolling_mean(s: pd.Series) -> pd.Series:
        return s.shift(1).rolling(window=window, min_periods=1).mean()

    grouped = tg.groupby("team", sort=False)
    tg["form_margin"] = grouped["margin"].transform(_shifted_rolling_mean)
    tg["form_total"] = grouped["total"].transform(_shifted_rolling_mean)
    tg["form_winpct"] = grouped["won"].transform(_shifted_rolling_mean)
    tg["form_n"] = grouped.cumcount()
    return tg[["game_id", "team", "form_margin", "form_total", "form_winpct", "form_n"]]


def _attach_feature_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["elo_home"] = out["home_elo_pre"]
    out["elo_away"] = out["away_elo_pre"]
    out["elo_diff"] = out["home_elo_pre"] - out["away_elo_pre"]
    out["home_off_elo"] = out["home_off_elo_pre"]
    out["away_off_elo"] = out["away_off_elo_pre"]
    out["home_def_elo"] = out["home_def_elo_pre"]
    out["away_def_elo"] = out["away_def_elo_pre"]
    out["off_elo_diff"] = out["home_off_elo_pre"] - out["away_off_elo_pre"]
    out["def_elo_diff"] = out["home_def_elo_pre"] - out["away_def_elo_pre"]
    out["is_playoff"] = (out["seasontype"] == "po").astype(int)
    out["elo_diff_x_playoff"] = out["elo_diff"] * out["is_playoff"]
    out["expected_form_total"] = out["home_form_off"] + out["away_form_off"]
    out["form_off_diff"] = out["home_form_off"] - out["away_form_off"]
    for col, default in _CONTEXT_DEFAULTS.items():
        if col in out.columns:
            out[col] = out[col].fillna(default)
    out = add_po_interaction_columns(out)
    return out


def build_training_table(
    games_with_elo: pd.DataFrame,
    team_games: pd.DataFrame,
    window: int = 10,
) -> pd.DataFrame:
    """Per-game training rows with features and targets, leak-free."""
    form = _rolling_form_table(team_games, window=window)
    home_form = form.rename(
        columns={
            "team": "home_tricode",
            "form_margin": "home_form_margin",
            "form_total": "home_form_total",
            "form_winpct": "home_form_winpct",
            "form_n": "home_form_n",
        }
    )
    away_form = form.rename(
        columns={
            "team": "away_tricode",
            "form_margin": "away_form_margin",
            "form_total": "away_form_total",
            "form_winpct": "away_form_winpct",
            "form_n": "away_form_n",
        }
    )

    df = games_with_elo.merge(home_form, on=["game_id", "home_tricode"], how="left")
    df = df.merge(away_form, on=["game_id", "away_tricode"], how="left")
    defaults = _league_default(window)
    for side in ("home", "away"):
        df[f"{side}_form_margin"] = df[f"{side}_form_margin"].fillna(defaults["form_margin"])
        df[f"{side}_form_total"] = df[f"{side}_form_total"].fillna(defaults["form_total"])
        df[f"{side}_form_winpct"] = df[f"{side}_form_winpct"].fillna(defaults["form_winpct"])

    df = enrich_games(df, team_games, window=window)
    df = _attach_feature_columns(df)

    df[TARGET_TOTAL] = df["home_final"] + df["away_final"]
    df[TARGET_MARGIN] = df["home_final"] - df["away_final"]

    keep = [
        "game_id",
        "season_start_year",
        "seasontype",
        "home_tricode",
        "away_tricode",
        "home_final",
        "away_final",
        TARGET_TOTAL,
        TARGET_MARGIN,
        *FEATURE_COLUMNS,
        "home_form_n",
        "away_form_n",
    ]
    return df[keep].copy()


def _series_game_n_live(
    team_games: pd.DataFrame,
    home: str,
    away: str,
    *,
    is_playoff: bool,
) -> float:
    if not is_playoff:
        return 0.0
    tg = team_games[team_games["seasontype"] == "po"].sort_values("game_id")
    pair_games = tg[
        ((tg["team"] == home) & (tg["opponent"] == away))
        | ((tg["team"] == away) & (tg["opponent"] == home))
    ]
    return float(len(pair_games) + 1)


def _current_form(team_games: pd.DataFrame, team: str, window: int) -> dict[str, float]:
    rows = team_games[team_games["team"] == team].sort_values("game_id").tail(window)
    defaults = _league_default(window)
    if rows.empty:
        return {
            "form_margin": defaults["form_margin"],
            "form_total": defaults["form_total"],
            "form_winpct": defaults["form_winpct"],
            "n_games": 0,
        }
    return {
        "form_margin": float(rows["margin"].mean()),
        "form_total": float(rows["total"].mean()),
        "form_winpct": float(rows["won"].mean()),
        "n_games": int(len(rows)),
    }


def build_inference_row(
    *,
    home: str,
    away: str,
    elo_state,
    offdef_state,
    team_games: pd.DataFrame,
    is_playoff: bool,
    window: int = 10,
) -> pd.Series:
    home_f = _current_form(team_games, home.upper(), window)
    away_f = _current_form(team_games, away.upper(), window)
    defaults = _league_default(window)

    hc = current_team_context(team_games, home.upper(), window=window)
    ac = current_team_context(team_games, away.upper(), window=window)
    h2h_total, h2h_margin = current_h2h(team_games, home.upper(), away.upper(), window=3)

    elo_home = float(elo_state.rating(home))
    elo_away = float(elo_state.rating(away))
    elo_diff = elo_home - elo_away
    is_po = int(bool(is_playoff))

    row = {
        "elo_home": elo_home,
        "elo_away": elo_away,
        "elo_diff": elo_diff,
        "home_off_elo": float(offdef_state.off_rating(home)),
        "away_off_elo": float(offdef_state.off_rating(away)),
        "home_def_elo": float(offdef_state.def_rating(home)),
        "away_def_elo": float(offdef_state.def_rating(away)),
        "off_elo_diff": float(offdef_state.off_rating(home) - offdef_state.off_rating(away)),
        "def_elo_diff": float(offdef_state.def_rating(home) - offdef_state.def_rating(away)),
        "elo_diff_x_playoff": elo_diff * is_po,
        "home_form_margin": home_f["form_margin"],
        "home_form_total": home_f["form_total"],
        "home_form_winpct": home_f["form_winpct"],
        "away_form_margin": away_f["form_margin"],
        "away_form_total": away_f["form_total"],
        "away_form_winpct": away_f["form_winpct"],
        "home_form_off": hc["form_off"],
        "away_form_off": ac["form_off"],
        "home_form_def": hc["form_def"],
        "away_form_def": ac["form_def"],
        "form_off_diff": hc["form_off"] - ac["form_off"],
        "expected_form_total": hc["form_off"] + ac["form_off"],
        "home_form_total_std": hc["form_total_std"],
        "away_form_total_std": ac["form_total_std"],
        "home_form_margin_std": hc["form_margin_std"],
        "away_form_margin_std": ac["form_margin_std"],
        "form_def_diff": hc["form_def"] - ac["form_def"],
        "home_form_q4_pace": hc["form_q4_pace"],
        "away_form_q4_pace": ac["form_q4_pace"],
        "form_q4_pace_diff": hc["form_q4_pace"] - ac["form_q4_pace"],
        "expected_q4_pace": (hc["form_q4_pace"] + ac["form_q4_pace"]) / 2.0,
        "home_win_streak": hc["win_streak"],
        "away_win_streak": ac["win_streak"],
        "home_rest_days": hc["rest_days"],
        "away_rest_days": ac["rest_days"],
        "home_is_back_to_back": hc["is_back_to_back"],
        "away_is_back_to_back": ac["is_back_to_back"],
        "home_po_game_n": hc["po_game_n"],
        "away_po_game_n": ac["po_game_n"],
        "series_game_n": _series_game_n_live(team_games, home.upper(), away.upper(), is_playoff=is_playoff),
        "h2h_avg_total": h2h_total,
        "h2h_home_margin": h2h_margin,
        "is_playoff": is_po,
        "_home_form_n": home_f["n_games"],
        "_away_form_n": away_f["n_games"],
    }
    return add_po_interaction_features(pd.Series(row))


def feature_row_to_frame(row: pd.Series) -> pd.DataFrame:
    row = add_po_interaction_features(row) if "series_x_elo_diff" not in row else row
    return pd.DataFrame([{c: float(row[c]) for c in FEATURE_COLUMNS}], columns=FEATURE_COLUMNS)
