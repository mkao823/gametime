"""Augment team_games with schedule dates and Q4 pace before pregame features."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from gametime.data.game_dates import attach_game_dates, load_or_fetch_game_dates
from gametime.pregame.q4_pace import LEAGUE_Q4_PACE48, load_or_build_q4_pace


def augment_team_games(
    team_games: pd.DataFrame,
    *,
    raw_dir: Path,
    processed_dir: Path,
    seasons: Iterable[int],
    v3_archive_seasons: Iterable[int] | None = None,
    refresh_dates: bool = False,
    refresh_q4: bool = False,
) -> pd.DataFrame:
    processed_dir = Path(processed_dir)
    date_seasons = sorted({int(s) for s in seasons})
    dates = load_or_fetch_game_dates(
        processed_dir / "game_dates.parquet",
        date_seasons,
        refresh=refresh_dates,
    )
    out = attach_game_dates(team_games, dates)

    q4 = load_or_build_q4_pace(
        processed_dir / "q4_pace.parquet",
        raw_dir,
        seasons=seasons,
        seasontype="both",
        v3_archive_seasons=v3_archive_seasons,
        refresh=refresh_q4,
    )
    if not q4.empty:
        out = out.merge(q4, on="game_id", how="left")
    if "q4_pace48" not in out.columns:
        out["q4_pace48"] = LEAGUE_Q4_PACE48
    else:
        out["q4_pace48"] = out["q4_pace48"].fillna(LEAGUE_Q4_PACE48)
    return out
