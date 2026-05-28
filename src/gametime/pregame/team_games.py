"""Build team_games.parquet: one row per (game_id, team) with finals and metadata.

Tricodes come from the raw PBP CSVs (HOMEDESCRIPTION / VISITORDESCRIPTION rows
identify which team is home vs. away). Final scores come from snapshots.parquet,
which the existing pipeline keeps current across all available seasons/types.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from gametime.data.game_meta import annotate_games
from gametime.sports import SportProfile
from gametime.data.nbastatsv3 import load_v3_games

PBP_COLS_FOR_TRICODE = [
    "GAME_ID",
    "HOMEDESCRIPTION",
    "VISITORDESCRIPTION",
    "PLAYER1_TEAM_ABBREVIATION",
]


def _normalize_game_id(series: pd.Series) -> pd.Series:
    return series.astype(str).str.zfill(10)


def _tricode_per_game(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df["GAME_ID"] = _normalize_game_id(df["GAME_ID"])

    def _dominant(side: str, out_col: str) -> pd.DataFrame:
        mask = df[side].notna() & df["PLAYER1_TEAM_ABBREVIATION"].notna()
        counts = (
            df.loc[mask]
            .groupby(["GAME_ID", "PLAYER1_TEAM_ABBREVIATION"])
            .size()
            .reset_index(name="n")
        )
        return (
            counts.sort_values(["GAME_ID", "n"], ascending=[True, False])
            .drop_duplicates("GAME_ID")
            .rename(columns={"PLAYER1_TEAM_ABBREVIATION": out_col})[["GAME_ID", out_col]]
        )

    home = _dominant("HOMEDESCRIPTION", "home_tricode")
    away = _dominant("VISITORDESCRIPTION", "away_tricode")
    return home.merge(away, on="GAME_ID", how="inner").rename(columns={"GAME_ID": "game_id"})


def _load_raw_minimal(
    raw_dir: Path,
    seasons: Iterable[int],
    seasontype: str,
    *,
    pbp_source: str = "nbastats",
) -> pd.DataFrame:
    frames = []
    types = ("rg", "po") if seasontype == "both" else (seasontype,)
    for st in types:
        for season in seasons:
            suffix = f"_{season}" if st == "rg" else f"_po_{season}"
            path = raw_dir / f"{pbp_source}{suffix}.csv"
            if path.exists():
                frames.append(
                    pd.read_csv(path, usecols=PBP_COLS_FOR_TRICODE, low_memory=False)
                )
    if not frames:
        raise FileNotFoundError(
            f"No PBP CSVs under {raw_dir} for seasons={list(seasons)} type={seasontype}"
        )
    return pd.concat(frames, ignore_index=True)


def build_team_games(
    raw_dir: Path,
    snapshots_path: Path,
    seasons: Iterable[int],
    seasontype: str = "both",
    *,
    pbp_source: str = "nbastats",
    v3_archive_seasons: Iterable[int] | None = None,
    league: SportProfile | None = None,
) -> pd.DataFrame:
    raw = _load_raw_minimal(raw_dir, seasons, seasontype, pbp_source=pbp_source)
    teams = _tricode_per_game(raw)

    sn = pd.read_parquet(snapshots_path)
    sn["game_id"] = _normalize_game_id(sn["game_id"])
    finals = (
        sn.drop_duplicates(subset="game_id")[["game_id", "home_final", "away_final"]].copy()
    )

    games = teams.merge(finals, on="game_id", how="inner")

    if v3_archive_seasons:
        v3 = load_v3_games(raw_dir, v3_archive_seasons)
        if not v3.empty:
            v3_games = v3[
                ["game_id", "home_tricode", "away_tricode", "home_final", "away_final",
                 "season_start_year", "seasontype"]
            ]
            known = set(games["game_id"])
            extra = v3_games[~v3_games["game_id"].isin(known)]
            if not extra.empty:
                games = pd.concat([games, extra], ignore_index=True)

    games = annotate_games(games, league=league)
    games = games.sort_values("game_id").reset_index(drop=True)

    home_cols = dict(
        team=games["home_tricode"],
        opponent=games["away_tricode"],
        is_home=1,
        points_for=games["home_final"].astype(float),
        points_against=games["away_final"].astype(float),
    )
    away_cols = dict(
        team=games["away_tricode"],
        opponent=games["home_tricode"],
        is_home=0,
        points_for=games["away_final"].astype(float),
        points_against=games["home_final"].astype(float),
    )

    keep = ["game_id", "season_start_year", "seasontype"]
    home_rows = games[keep].assign(**home_cols)
    away_rows = games[keep].assign(**away_cols)
    long = pd.concat([home_rows, away_rows], ignore_index=True)

    long["margin"] = long["points_for"] - long["points_against"]
    long["total"] = long["points_for"] + long["points_against"]
    long["won"] = (long["points_for"] > long["points_against"]).astype(int)
    long = long.sort_values(["team", "game_id"]).reset_index(drop=True)
    long["team_game_idx"] = long.groupby("team").cumcount()
    return long


def write_team_games(
    raw_dir: Path,
    snapshots_path: Path,
    out_path: Path,
    *,
    seasons: Iterable[int],
    seasontype: str = "both",
    pbp_source: str = "nbastats",
    v3_archive_seasons: Iterable[int] | None = None,
) -> Path:
    df = build_team_games(
        raw_dir,
        snapshots_path,
        seasons,
        seasontype,
        pbp_source=pbp_source,
        v3_archive_seasons=v3_archive_seasons,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    return out_path


def to_game_level(team_games: pd.DataFrame) -> pd.DataFrame:
    """Collapse the long-form table to one row per game with home/away columns."""
    h = team_games[team_games["is_home"] == 1].rename(
        columns={
            "team": "home_tricode",
            "opponent": "away_tricode",
            "points_for": "home_final",
            "points_against": "away_final",
        }
    )[
        [
            "game_id",
            "season_start_year",
            "seasontype",
            "home_tricode",
            "away_tricode",
            "home_final",
            "away_final",
        ]
    ]
    return h.sort_values("game_id").reset_index(drop=True)
