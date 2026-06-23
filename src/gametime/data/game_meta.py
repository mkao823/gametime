from __future__ import annotations

import pandas as pd

from gametime.sports import NBA, SportProfile

# NBA game_id: 002 = regular season, 004 = playoffs (stats.nba.com)
# WNBA game_id: 102 = regular season, 104 = playoffs
REGULAR_PREFIX = NBA.regular_game_id_prefix
PLAYOFF_PREFIX = NBA.playoff_game_id_prefix


def season_start_year(game_id: str) -> int:
    """e.g. 0022400928 -> 2024 (season 2024-25)."""
    gid = str(game_id).zfill(10)
    return 2000 + int(gid[3:5])


def seasontype_from_game_id(
    game_id: str,
    *,
    league: SportProfile | None = None,
    regular_prefix: str | None = None,
    playoff_prefix: str | None = None,
) -> str:
    spec = league or NBA
    rg = regular_prefix if regular_prefix is not None else spec.regular_game_id_prefix
    po = playoff_prefix if playoff_prefix is not None else spec.playoff_game_id_prefix
    gid = str(game_id).zfill(10)
    if gid.startswith(po):
        return "po"
    if gid.startswith(rg):
        return "rg"
    return "other"


def annotate_games(
    df: pd.DataFrame,
    game_id_col: str = "game_id",
    *,
    league: SportProfile | None = None,
) -> pd.DataFrame:
    out = df.copy()
    out["season_start_year"] = out[game_id_col].map(season_start_year)
    out["seasontype"] = out[game_id_col].map(
        lambda gid: seasontype_from_game_id(gid, league=league)
    )
    return out


def filter_games(
    df: pd.DataFrame,
    *,
    season: int | None = None,
    seasons: list[int] | None = None,
    seasontypes: list[str] | None = None,
    league: SportProfile | None = None,
) -> pd.DataFrame:
    if "season_start_year" in df.columns and "seasontype" in df.columns and league is None:
        out = df.copy()
    else:
        out = annotate_games(df, league=league)
    if season is not None:
        seasons = [season] if seasons is None else list(seasons) + [season]
    if seasons is not None:
        out = out[out["season_start_year"].isin(seasons)]
    if seasontypes is not None:
        out = out[out["seasontype"].isin(seasontypes)]
    return out
