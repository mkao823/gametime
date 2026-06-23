"""NBA game dates from stats.nba.com LeagueGameLog (cached parquet)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterable
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

STATS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Referer": "https://www.nba.com/",
    "Accept": "application/json",
    "Origin": "https://www.nba.com",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
}
LEAGUE_GAME_LOG = "https://stats.nba.com/stats/leaguegamelog"


def season_label(season_start_year: int) -> str:
    """2024 -> '2024-25'."""
    y = season_start_year
    return f"{y}-{str(y + 1)[-2:]}"


def _normalize_game_id(series: pd.Series) -> pd.Series:
    return series.astype(str).str.zfill(10)


def _fetch_season_log(season_start_year: int, season_type: str) -> pd.DataFrame:
    params = {
        "Counter": "0",
        "Direction": "ASC",
        "LeagueID": "00",
        "Season": season_label(season_start_year),
        "SeasonType": season_type,
        "Sorter": "DATE",
    }
    url = f"{LEAGUE_GAME_LOG}?{urlencode(params)}"
    req = Request(url, headers=STATS_HEADERS)
    with urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    headers = payload["resultSets"][0]["headers"]
    rows = payload["resultSets"][0]["rowSet"]
    df = pd.DataFrame(rows, columns=headers)
    if df.empty:
        return pd.DataFrame(columns=["game_id", "game_date"])
    out = pd.DataFrame(
        {
            "game_id": _normalize_game_id(df["GAME_ID"]),
            "game_date": pd.to_datetime(df["GAME_DATE"]).dt.normalize(),
        }
    )
    return out.drop_duplicates("game_id")


def fetch_game_dates(seasons: Iterable[int], *, pause_seconds: float = 0.6) -> pd.DataFrame:
    """Fetch RS + PO game dates for each season_start_year."""
    frames = []
    for season in seasons:
        for stype in ("Regular Season", "Playoffs"):
            try:
                chunk = _fetch_season_log(int(season), stype)
                if not chunk.empty:
                    frames.append(chunk)
            except (URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
                print(f"[game_dates] skip {season} {stype}: {exc}")
            time.sleep(pause_seconds)
    if not frames:
        return pd.DataFrame(columns=["game_id", "game_date"])
    return pd.concat(frames, ignore_index=True).drop_duplicates("game_id")


def load_or_fetch_game_dates(
    cache_path: Path,
    seasons: Iterable[int],
    *,
    refresh: bool = False,
) -> pd.DataFrame:
    cache_path = Path(cache_path)
    if cache_path.exists() and not refresh:
        return pd.read_parquet(cache_path)
    df = fetch_game_dates(seasons)
    if not df.empty:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache_path, index=False)
    return df


def attach_game_dates(team_games: pd.DataFrame, dates: pd.DataFrame) -> pd.DataFrame:
    if dates.empty:
        out = team_games.copy()
        out["game_date"] = pd.NaT
        return out
    d = dates.copy()
    d["game_id"] = _normalize_game_id(d["game_id"])
    out = team_games.copy()
    out["game_id"] = _normalize_game_id(out["game_id"])
    return out.merge(d, on="game_id", how="left")
