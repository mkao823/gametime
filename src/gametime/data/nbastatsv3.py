"""Load NBA Stats v3 play-by-play CSVs (different schema from classic nbastats)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import pandas as pd

from gametime.data.game_meta import annotate_games

ISO_CLOCK = re.compile(
    r"^PT(?P<min>\d+)M(?P<sec>\d+(?:\.\d+)?)S$",
    re.IGNORECASE,
)


def parse_v3_clock(clock: str) -> float | None:
    if pd.isna(clock) or not str(clock).strip():
        return None
    m = ISO_CLOCK.match(str(clock).strip())
    if not m:
        return None
    return int(m.group("min")) * 60 + float(m.group("sec"))


def _normalize_game_id(series: pd.Series) -> pd.Series:
    return series.astype(str).str.zfill(10)


def load_v3_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, low_memory=False)


def tricode_and_finals_from_v3(raw: pd.DataFrame) -> pd.DataFrame:
    """One row per game: home/away tricodes and final scores from v3 PBP."""
    df = raw.copy()
    df["game_id"] = _normalize_game_id(df["gameId"])

    home_tri = (
        df.loc[df["location"] == "h"]
        .groupby("game_id")["teamTricode"]
        .first()
        .rename("home_tricode")
    )
    away_tri = (
        df.loc[df["location"] == "v"]
        .groupby("game_id")["teamTricode"]
        .first()
        .rename("away_tricode")
    )
    teams = home_tri.to_frame().join(away_tri, how="inner")

    scored = df.dropna(subset=["scoreHome", "scoreAway"]).copy()
    scored["actionNumber"] = pd.to_numeric(scored["actionNumber"], errors="coerce")
    finals = (
        scored.sort_values(["game_id", "actionNumber"])
        .groupby("game_id")
        .tail(1)[["game_id", "scoreHome", "scoreAway"]]
        .rename(columns={"scoreHome": "home_final", "scoreAway": "away_final"})
        .set_index("game_id")
    )
    games = teams.join(finals, how="inner").reset_index()
    games = annotate_games(games)
    return games.sort_values("game_id").reset_index(drop=True)


def load_v3_games(raw_dir: Path, archive_seasons: Iterable[int]) -> pd.DataFrame:
    frames = []
    for season in archive_seasons:
        path = raw_dir / f"nbastatsv3_{season}.csv"
        if path.exists():
            frames.append(tricode_and_finals_from_v3(load_v3_csv(path)))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).drop_duplicates("game_id")
