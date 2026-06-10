"""MLB game logs for pregame training (no play-by-play).

Uses pybaseball schedule_and_record per team/season. Install: pip install -e '.[mlb]'.
"""
from __future__ import annotations

import hashlib
import re
import time
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Optional

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

# BR schedule slug: OAK through 2025, ATH from 2026 (Athletics relocation)
_ATHLETICS_BR_SWITCH_SEASON = 2026


def teams_for_season(
    season_start_year: int,
    base: Optional[Iterable[str]] = None,
) -> tuple[str, ...]:
    """pybaseball team codes for schedule_and_record (season-aware Athletics slug)."""
    src = tuple(base or DEFAULT_TEAMS)
    if int(season_start_year) >= _ATHLETICS_BR_SWITCH_SEASON:
        return tuple("ATH" if t == "OAK" else t for t in src)
    return src


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


def _seasontype_from_row(row: pd.Series) -> str:
    if "Postseason" in row.index and bool(row.get("Postseason")):
        return "po"
    inn = row.get("Inn", row.get("inn"))
    if inn is not None and not pd.isna(inn) and str(inn).strip().lower() in ("", "nan"):
        return "po"
    return "rg"


def _home_away_from_row(row: pd.Series, team: str, opp: str) -> tuple[str, str]:
    loc = str(row.get("Home_Away", row.get("home_away", "Home"))).strip().lower()
    is_home = loc in ("home", "h")
    if is_home:
        return team, opp
    return opp, team


def infer_season_start_year(game_date: date) -> int:
    """Map a calendar date to MLB season_start_year (same label as ingest)."""
    return game_date.year if game_date.month >= 3 else game_date.year - 1


def _parse_schedule_matchup(
    row: pd.Series,
    team: str,
    season_start_year: int,
) -> Optional[dict]:
    """Schedule row → matchup metadata (includes unplayed games)."""
    opp_col = "Opp" if "Opp" in row.index else "opp"
    if opp_col not in row.index:
        return None
    opp = _norm_team(str(row[opp_col]))
    team = _norm_team(team)

    date_val = row.get("Date") or row.get("date")
    if date_val is None or pd.isna(date_val):
        return None
    try:
        game_date = _parse_game_date(date_val, season_start_year)
    except (ValueError, pd.errors.OutOfBoundsDatetime):
        return None

    home, away = _home_away_from_row(row, team, opp)
    seasontype = _seasontype_from_row(row)
    gid = _game_id(game_date, home, away)
    return {
        "game_id": gid,
        "game_date": game_date,
        "home_team": home,
        "away_team": away,
        "season_start_year": season_start_year,
        "seasontype": seasontype,
    }


def slate_from_games_parquet(
    games: pd.DataFrame,
    target_date: date,
    *,
    regular_season_only: bool = True,
) -> list[dict[str, str]]:
    """Matchups on target_date from processed games (completed games only)."""
    if games.empty:
        return []
    df = games.copy()
    df["game_date"] = pd.to_datetime(df["game_date"]).dt.normalize()
    td = pd.Timestamp(target_date).normalize()
    sub = df[df["game_date"] == td]
    if regular_season_only:
        sub = sub[sub["seasontype"] == "rg"]
    if sub.empty:
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for _, row in sub.iterrows():
        gid = str(row["game_id"])
        if gid in seen:
            continue
        seen.add(gid)
        out.append(
            {
                "game_id": gid,
                "away": str(row["away_team"]),
                "home": str(row["home_team"]),
            }
        )
    return out


def fetch_slate_from_pybaseball(
    target_date: date,
    season_start_year: int,
    teams: Optional[Iterable[str]] = None,
    *,
    regular_season_only: bool = True,
    pause: float = 0.4,
) -> list[dict[str, str]]:
    """Discover matchups on a date via team schedules (includes upcoming games)."""
    try:
        from pybaseball import cache
        from pybaseball import schedule_and_record
    except ImportError as exc:
        raise ImportError(
            "MLB slate requires pybaseball. Install with: pip install -e '.[mlb]'"
        ) from exc

    cache.enable()
    td = pd.Timestamp(target_date).normalize()
    team_list = list(teams_for_season(season_start_year, teams))
    by_id: dict[str, dict[str, str]] = {}

    for team in team_list:
        try:
            df = schedule_and_record(season_start_year, team)
        except Exception as exc:
            print(f"[mlb] slate skip {team} {season_start_year}: {exc}")
            continue
        time.sleep(pause)
        if df is None or df.empty:
            continue
        for _, row in df.iterrows():
            parsed = _parse_schedule_matchup(row, team, season_start_year)
            if parsed is None:
                continue
            if parsed["game_date"] != td:
                continue
            if regular_season_only and parsed["seasontype"] != "rg":
                continue
            gid = parsed["game_id"]
            by_id[gid] = {
                "game_id": gid,
                "away": parsed["away_team"],
                "home": parsed["home_team"],
            }

    return list(by_id.values())


def _slate_sort_key(matchup: dict[str, Any]) -> tuple[Any, ...]:
    start_time = matchup.get("start_time")
    return (start_time is None, start_time or "", matchup["away"], matchup["home"])


def _attach_and_sort_slate_matchups(
    matchups: list[dict[str, str]],
    target_date: date,
) -> list[dict[str, Any]]:
    from gametime.ingest.mlb_schedule import (
        fetch_slate_times_for_date,
        lookup_slate_time_for_matchup,
    )

    times = fetch_slate_times_for_date(target_date)
    enriched: list[dict[str, Any]] = []
    for m in matchups:
        row = dict(m)
        row["start_time"] = lookup_slate_time_for_matchup(times, m["away"], m["home"])
        enriched.append(row)
    enriched.sort(key=_slate_sort_key)
    return enriched


def slate_matchups_for_date(
    target_date: date,
    *,
    season_start_year: Optional[int] = None,
    games_path: Optional[Path] = None,
    teams: Optional[Iterable[str]] = None,
    regular_season_only: bool = True,
) -> list[dict[str, Any]]:
    """Matchups for a calendar day: parquet when available, else pybaseball schedules."""
    season = season_start_year or infer_season_start_year(target_date)
    matchups: list[dict[str, str]] = []
    if games_path is not None and Path(games_path).exists():
        games = pd.read_parquet(games_path)
        found = slate_from_games_parquet(
            games, target_date, regular_season_only=regular_season_only
        )
        if found:
            matchups = found
    if not matchups:
        matchups = fetch_slate_from_pybaseball(
            target_date,
            season,
            teams=teams,
            regular_season_only=regular_season_only,
        )
    if not matchups:
        return []
    return _attach_and_sort_slate_matchups(matchups, target_date)


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

    home, away = _home_away_from_row(row, team, opp)
    if home == team:
        hr, ar = float(home_runs), float(away_runs)
    else:
        hr, ar = float(away_runs), float(home_runs)

    date_val = row.get("Date") or row.get("date")
    if date_val is None or pd.isna(date_val):
        return None
    try:
        game_date = _parse_game_date(date_val, season_start_year)
    except (ValueError, pd.errors.OutOfBoundsDatetime):
        return None

    seasontype = _seasontype_from_row(row)

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
    frames = []
    for season in seasons:
        season_teams = list(teams_for_season(season, teams))
        for team in season_teams:
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
    statsapi_backfill_days: int = 14,
    statsapi_game_types: Optional[list[str]] = None,
    statsapi_postseason_enabled: bool = False,
    statsapi_postseason_types: Optional[list[str]] = None,
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    games = build_games_table(seasons, teams)
    if games.empty:
        raise ValueError(f"No MLB games fetched for seasons={seasons}")

    from gametime.ingest.mlb_statsapi_games import merge_statsapi_into_games

    rs_types = tuple(statsapi_game_types or ("R",))
    po_types: tuple[str, ...] = ()
    if statsapi_postseason_enabled:
        po_types = tuple(statsapi_postseason_types or ("P", "F", "W", "D", "L"))

    games = merge_statsapi_into_games(
        games,
        backfill_days=int(statsapi_backfill_days),
        game_types=rs_types,
        postseason_types=po_types,
    )
    if games.empty:
        raise ValueError(f"No MLB games after pybaseball + Stats API merge seasons={seasons}")

    games.to_parquet(out_path, index=False)
    print(f"[mlb] Wrote {len(games)} games → {out_path}")
    return out_path
