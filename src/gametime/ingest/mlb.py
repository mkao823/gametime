"""MLB game logs for pregame training (no play-by-play).

Uses pybaseball schedule_and_record per team/season. Install: pip install -e '.[mlb]'.
"""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

_DATE_NO_YEAR = re.compile(
    r"^[A-Za-z]+,\s+(?P<mon>[A-Za-z]+)\s+(?P<day>\d{1,2})$"
)

# Team codes used by pybaseball / Baseball Reference
DEFAULT_TEAMS = (
    "ARI", "ATL", "BAL", "BOS", "CHC", "CHW", "CIN", "CLE", "COL", "DET",
    "HOU", "KCR", "LAA", "LAD", "MIA", "MIL", "MIN", "NYM", "NYY", "OAK",
    "PHI", "PIT", "SDP", "SEA", "SFG", "STL", "TBR", "TEX", "TOR", "WSN",
)

# Normalize pybaseball abbreviations → canonical
_TEAM_ALIASES = {
    "AZ": "ARI",
    "CHC": "CHC",
    "CWS": "CHW",
    "KC": "KCR",
    "SD": "SDP",
    "SF": "SFG",
    "TB": "TBR",
    "WSH": "WSN",
}


def _parse_game_date(date_val, season_start_year: int) -> pd.Timestamp:
    if isinstance(date_val, pd.Timestamp):
        return date_val.normalize()
    text = str(date_val).strip()
    try:
        return pd.to_datetime(text).normalize()
    except (ValueError, pd.errors.OutOfBoundsDatetime):
        pass
    m = _DATE_NO_YEAR.match(text)
    if m:
        return pd.to_datetime(
            f"{m.group('mon')} {m.group('day')} {season_start_year}",
            format="%b %d %Y",
        ).normalize()
    ts = pd.to_datetime(text, errors="coerce")
    if pd.isna(ts):
        raise ValueError(f"unparseable game date: {text!r}")
    return ts.normalize()


def _norm_team(code: str) -> str:
    c = str(code).strip().upper()
    return _TEAM_ALIASES.get(c, c)


def _game_id(game_date: pd.Timestamp, home: str, away: str) -> str:
    key = f"{game_date.date().isoformat()}|{home}|{away}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def _parse_schedule_row(
    row: pd.Series,
    team: str,
    season_start_year: int,
) -> Optional[dict]:
    """One team-schedule row → half of a game (home or away perspective)."""
    opp_col = "Opp" if "Opp" in row.index else "opp"
    if opp_col not in row.index:
        return None
    opp = _norm_team(str(row[opp_col]))
    team = _norm_team(team)

    home_runs = row.get("R")
    away_runs = row.get("RA")
    if pd.isna(home_runs) or pd.isna(away_runs):
        return None

    loc = str(row.get("Home_Away", row.get("home_away", "Home"))).strip().lower()
    is_home = loc in ("home", "h")
    if is_home:
        home, away = team, opp
        hr, ar = float(home_runs), float(away_runs)
    else:
        home, away = opp, team
        hr, ar = float(away_runs), float(home_runs)

    date_val = row.get("Date") or row.get("date")
    if date_val is None or pd.isna(date_val):
        return None
    try:
        game_date = _parse_game_date(date_val, season_start_year)
    except (ValueError, pd.errors.OutOfBoundsDatetime):
        return None

    inn = row.get("Inn", row.get("inn"))
    seasontype = "po" if inn is not None and str(inn).strip().lower() in ("", "nan") else "rg"
    # Playoff games often tagged in Opp or separate — use postseason flag when present
    if "Postseason" in row.index and bool(row.get("Postseason")):
        seasontype = "po"

    gid = _game_id(game_date, home, away)
    return {
        "game_id": gid,
        "game_date": game_date,
        "home_team": home,
        "away_team": away,
        "home_runs": hr,
        "away_runs": ar,
        "total_final": hr + ar,
        "margin_final": hr - ar,
        "season_start_year": season_start_year,
        "seasontype": seasontype,
    }


def fetch_team_season(team: str, season_start_year: int, *, pause: float = 0.4) -> pd.DataFrame:
    try:
        from pybaseball import cache
        from pybaseball import schedule_and_record
    except ImportError as exc:
        raise ImportError(
            "MLB ingest requires pybaseball. Install with: pip install -e '.[mlb]'"
        ) from exc

    cache.enable()
    # pybaseball season arg is the ending year (2024 season → 2024)
    df = schedule_and_record(season_start_year, team)
    time.sleep(pause)
    if df is None or df.empty:
        return pd.DataFrame()
    rows = []
    for _, row in df.iterrows():
        parsed = _parse_schedule_row(row, team, season_start_year)
        if parsed:
            rows.append(parsed)
    return pd.DataFrame(rows)


def build_games_table(
    seasons: Iterable[int],
    teams: Optional[Iterable[str]] = None,
) -> pd.DataFrame:
    teams = list(teams or DEFAULT_TEAMS)
    frames = []
    for season in seasons:
        for team in teams:
            try:
                chunk = fetch_team_season(team, int(season))
                if not chunk.empty:
                    frames.append(chunk)
            except Exception as exc:
                print(f"[mlb] skip {team} {season}: {exc}")
    if not frames:
        return pd.DataFrame(
            columns=[
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
        )
    games = pd.concat(frames, ignore_index=True)
    games = games.drop_duplicates("game_id").sort_values("game_date").reset_index(drop=True)
    return games


def download_mlb_games(
    out_path: Path,
    *,
    seasons: list[int],
    teams: Optional[list[str]] = None,
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    games = build_games_table(seasons, teams)
    if games.empty:
        raise ValueError(f"No MLB games fetched for seasons={seasons}")
    games.to_parquet(out_path, index=False)
    print(f"[mlb] Wrote {len(games)} games → {out_path}")
    return out_path
