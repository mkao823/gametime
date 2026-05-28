"""Join causal pre-game model outputs onto in-game snapshot rows."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from gametime.pregame.augment import augment_team_games
from gametime.pregame.elo import EloParams, fit_elo, fit_off_def_elo
from gametime.pregame.features import (
    FEATURE_COLUMNS as PREGAME_FEATURE_COLUMNS,
    build_training_table,
)
from gametime.pregame.score import (
    load_band_calibration_if_present,
    load_calibration_if_present,
    load_pregame_boosters,
    score_feature_frame,
)
from gametime.pregame.team_games import build_team_games, write_team_games

PREGAME_JOIN_COLUMNS = [
    "pregame_pred_total",
    "pregame_pred_margin",
    "elo_diff",
    "naive_vs_pregame",
    "pregame_margin_band_width",
    "pregame_blowout_prob",
]

PREGAME_FEATURE_DEFAULTS = {
    "pregame_pred_total": 225.8,
    "pregame_pred_margin": 0.0,
    "elo_diff": 0.0,
    "naive_vs_pregame": 0.0,
    "pregame_margin_band_width": 16.0,
    "pregame_blowout_prob": 0.0,
}


def build_pregame_lookup(
    root: Path,
    *,
    raw_dir: Path,
    snapshots_path: Path,
    team_games_path: Path,
    pregame_model_dir: Path,
    seasons: list[int],
    form_window: int = 10,
    elo_params: Optional[EloParams] = None,
    rebuild_team_games: bool = False,
    v3_archive_seasons: Optional[list[int]] = None,
    pbp_source: str = "nbastats",
    league=None,
) -> pd.DataFrame:
    """One row per game_id with causal pregame predictions (same for all snapshots)."""
    pregame_model_dir = Path(pregame_model_dir)
    boosters = load_pregame_boosters(pregame_model_dir)
    calibration = load_calibration_if_present(pregame_model_dir)
    band_calibration = load_band_calibration_if_present(pregame_model_dir)

    team_games_path = Path(team_games_path)
    if rebuild_team_games or not team_games_path.exists():
        write_team_games(
            raw_dir,
            snapshots_path,
            team_games_path,
            seasons=seasons,
            seasontype="both",
            pbp_source=pbp_source,
            v3_archive_seasons=v3_archive_seasons,
        )

    team_games = pd.read_parquet(team_games_path)
    processed_dir = snapshots_path.parent
    team_games = augment_team_games(
        team_games,
        raw_dir=raw_dir,
        processed_dir=processed_dir,
        seasons=seasons,
        v3_archive_seasons=v3_archive_seasons,
    )
    params = elo_params or EloParams()
    games_elo, _ = fit_elo(team_games, params=params)
    games_offdef, _ = fit_off_def_elo(team_games, params=params)
    off_cols = [
        "game_id",
        "home_off_elo_pre",
        "away_off_elo_pre",
        "home_def_elo_pre",
        "away_def_elo_pre",
    ]
    games = games_elo.merge(games_offdef[off_cols], on="game_id", how="left")
    table = build_training_table(games, team_games, window=form_window)

    scored = score_feature_frame(
        table[PREGAME_FEATURE_COLUMNS],
        boosters,
        calibration=calibration,
        band_calibration=band_calibration,
    )
    table = table.copy()
    for col in (
        "pregame_pred_total",
        "pregame_pred_margin",
        "pregame_margin_band_width",
        "pregame_blowout_prob",
    ):
        table[col] = scored[col].to_numpy()
    table["elo_diff"] = table["elo_diff"].astype(float)

    return table[
        ["game_id", "pregame_pred_total", "pregame_pred_margin", "elo_diff",
         "pregame_margin_band_width", "pregame_blowout_prob"]
    ].drop_duplicates("game_id")


def add_pregame_feature_defaults(
    snapshots: pd.DataFrame,
    *,
    league_total_fallback: float = 225.8,
) -> pd.DataFrame:
    """Fill pregame join columns when no pregame model is trained yet."""
    lookup = pd.DataFrame({"game_id": snapshots["game_id"].drop_duplicates()})
    return add_pregame_features(snapshots, lookup, league_total_fallback=league_total_fallback)


def add_pregame_features(
    snapshots: pd.DataFrame,
    lookup: pd.DataFrame,
    *,
    league_total_fallback: float = 225.8,
) -> pd.DataFrame:
    out = snapshots.merge(lookup, on="game_id", how="left")
    defaults = dict(PREGAME_FEATURE_DEFAULTS)
    defaults["pregame_pred_total"] = league_total_fallback
    for col in PREGAME_JOIN_COLUMNS:
        if col == "naive_vs_pregame":
            continue
        if col not in out.columns:
            out[col] = defaults[col]
        else:
            out[col] = out[col].fillna(defaults[col])
    out["naive_vs_pregame"] = out["naive_recent_total_final"] - out["pregame_pred_total"]
    return out


def attach_pregame_to_row(
    row: pd.Series,
    *,
    pregame_pred_total: float,
    pregame_pred_margin: float,
    elo_diff: float,
    pregame_margin_band_width: float = 16.0,
    pregame_blowout_prob: float = 0.0,
) -> pd.Series:
    out = row.copy()
    out["pregame_pred_total"] = float(pregame_pred_total)
    out["pregame_pred_margin"] = float(pregame_pred_margin)
    out["elo_diff"] = float(elo_diff)
    out["pregame_margin_band_width"] = float(pregame_margin_band_width)
    out["pregame_blowout_prob"] = float(pregame_blowout_prob)
    out["naive_vs_pregame"] = float(row["naive_recent_total_final"]) - float(pregame_pred_total)
    return out
