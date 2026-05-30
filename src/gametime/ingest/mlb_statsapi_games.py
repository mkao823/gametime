"""MLB Stats API gap-fill for games.parquet (M0 hybrid ingest).

pybaseball / Baseball Reference can lag 1–3 days on final scores. After each
bulk rebuild, pull **Final** games from statsapi.mlb.com through yesterday and
re-fetch the last N calendar days to pick up score corrections.

Postseason gameType codes (when ``games_statsapi_postseason_enabled``):
  P — Wild Card, F — Division Series, W — League Championship, D — Division
  Series (alt), L — League Championship (alt). All map to ``seasontype=po``.
  R — Regular season → ``seasontype=rg``.
"""
from __future__ import annotations

import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from gametime.ingest.mlb import _game_id, infer_season_start_year
from gametime.ingest.mlb_pitchers import MLB_STATS_BASE, _canon_from_mlb_api, _http_json

# MLB schedule gameType → gametime seasontype
_GAME_TYPE_SEASONTYPE: dict[str, str] = {
    "R": "rg",
    "P": "po",
    "F": "po",
    "W": "po",
    "D": "po",
    "L": "po",
}

_GAMES_COLUMNS = [
    "game_id",
    "game_date",
    "home_team",
    "away_team",
    "home_runs",
    "away_runs",
    "total_final",
    "margin_final",
    "season_start_year",
    "seasontype",
]


def seasontype_for_game_type(game_type: str) -> str:
    """Map MLB Stats API ``gameType`` to gametime ``seasontype``."""
    return _GAME_TYPE_SEASONTYPE.get(str(game_type).strip().upper(), "po")


def _fetch_linescore_runs(game_pk: int) -> tuple[int, int]:
    url = f"{MLB_STATS_BASE}/game/{game_pk}/linescore"
    payload = _http_json(url)
    teams = payload.get("teams") or {}
    home_runs = int((teams.get("home") or {}).get("runs", 0) or 0)
    away_runs = int((teams.get("away") or {}).get("runs", 0) or 0)
    return home_runs, away_runs


def _schedule_url(game_date: date, game_type: str) -> str:
    return (
        f"{MLB_STATS_BASE}/schedule?sportId=1&date={game_date.isoformat()}"
        f"&gameType={game_type}&hydrate=team"
    )


def fetch_final_games_for_date(
    game_date: date,
    *,
    game_types: tuple[str, ...] = ("R",),
    pause: float = 0.15,
) -> list[dict[str, Any]]:
    """Final games on ``game_date`` for the given ``gameType`` codes."""
    rows: list[dict[str, Any]] = []
    seen_pks: set[int] = set()

    for game_type in game_types:
        payload = _http_json(_schedule_url(game_date, game_type))
        for day in payload.get("dates", []):
            for g in day.get("games", []):
                if g.get("status", {}).get("abstractGameState") != "Final":
                    continue
                game_pk = int(g["gamePk"])
                if game_pk in seen_pks:
                    continue
                seen_pks.add(game_pk)

                home_abbr = g["teams"]["home"]["team"].get("abbreviation") or ""
                away_abbr = g["teams"]["away"]["team"].get("abbreviation") or ""
                home = _canon_from_mlb_api(home_abbr)
                away = _canon_from_mlb_api(away_abbr)
                ts = pd.Timestamp(game_date).normalize()
                home_runs, away_runs = _fetch_linescore_runs(game_pk)
                if pause > 0:
                    time.sleep(pause)

                gt = str(g.get("gameType") or game_type).strip().upper()
                rows.append(
                    {
                        "game_id": _game_id(ts, home, away),
                        "game_date": ts,
                        "home_team": home,
                        "away_team": away,
                        "home_runs": home_runs,
                        "away_runs": away_runs,
                        "total_final": home_runs + away_runs,
                        "margin_final": home_runs - away_runs,
                        "season_start_year": infer_season_start_year(game_date),
                        "seasontype": seasontype_for_game_type(gt),
                    }
                )
    return rows


def backfill_games_from_statsapi(
    games_path: Optional[Path],
    *,
    start_date: date,
    end_date: date,
    game_types: tuple[str, ...] = ("R",),
    pause: float = 0.15,
) -> pd.DataFrame:
    """Collect Final games for each date in ``[start_date, end_date]`` inclusive."""
    _ = games_path  # reserved for future disk cache
    if start_date > end_date:
        return pd.DataFrame(columns=_GAMES_COLUMNS)

    rows: list[dict[str, Any]] = []
    cur = start_date
    while cur <= end_date:
        rows.extend(
            fetch_final_games_for_date(cur, game_types=game_types, pause=pause)
        )
        cur += timedelta(days=1)

    if not rows:
        return pd.DataFrame(columns=_GAMES_COLUMNS)
    out = pd.DataFrame(rows)
    return out.drop_duplicates("game_id", keep="last").reset_index(drop=True)


def _backfill_date_range(
    max_date: Optional[date],
    *,
    backfill_days: int,
    end_date: date,
) -> tuple[date, date]:
    """Union of gap-fill (after max_date) and rolling correction window."""
    corr_start = end_date - timedelta(days=max(backfill_days, 1) - 1)
    if max_date is None:
        return corr_start, end_date
    gap_start = max_date + timedelta(days=1)
    start = min(gap_start, corr_start)
    if start > end_date:
        start = corr_start
    return start, end_date


def merge_statsapi_into_games(
    games: pd.DataFrame,
    *,
    backfill_days: int = 14,
    game_types: tuple[str, ...] = ("R",),
    postseason_types: tuple[str, ...] = (),
    end_date: Optional[date] = None,
    pause: float = 0.15,
) -> pd.DataFrame:
    """Append/replace recent rows from MLB Stats API; dedupe on ``game_id``."""
    end = end_date or (date.today() - timedelta(days=1))
    max_date: Optional[date] = None
    if not games.empty and "game_date" in games.columns:
        max_date = pd.to_datetime(games["game_date"]).max().date()

    all_types = tuple(dict.fromkeys((*game_types, *postseason_types)))
    start, end = _backfill_date_range(
        max_date, backfill_days=backfill_days, end_date=end
    )

    api_games = backfill_games_from_statsapi(
        None,
        start_date=start,
        end_date=end,
        game_types=all_types,
        pause=pause,
    )

    if api_games.empty:
        return games

    merged = pd.concat([games, api_games], ignore_index=True)
    merged = merged.drop_duplicates("game_id", keep="last")
    merged = merged.sort_values("game_date").reset_index(drop=True)
    print(
        f"[mlb-statsapi] appended {len(api_games)} games "
        f"({start.isoformat()} → {end.isoformat()})"
    )
    return merged
