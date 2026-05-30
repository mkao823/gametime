"""Starting-pitcher ingest for MLB pregame (M1).

Sources:
  - MLB Stats API (statsapi.mlb.com): schedule + boxscore for starter IDs and
    game pitching lines. No API key; cache responses under data/mlb/raw/.
  - pybaseball pitching_stats_bref / pitching_stats_range: fallback season FIP
    when cumulative game lines are unavailable (rate-limited; uses cache.enable).

Pre-game discipline:
  - Starter FIP for game G uses only pitching lines from games strictly before G.
  - Rest days = calendar days since the pitcher's previous start (not including G).

Training attaches per-game sidecar columns (``home_sp_fip`` / ``away_sp_fip``) via
``attach_pitcher()`` — do not change that join semantics.

Live slate inference resolves probable SP IDs from the schedule API, then looks up
each pitcher's last pre-game FIP from the sidecar with ``fip_prior_for_pitcher_id()``
(as-of slate date, strictly before that date). Do not rebuild cumulative stats from
synthetic IP for inference.

Default coverage: seasons >= min_season (2024+). Extend min_season for full history.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from gametime.ingest.mlb import _norm_team

MLB_STATS_BASE = "https://statsapi.mlb.com/api/v1"
LEAGUE_FIP = 4.20
FIP_CONSTANT = 3.10
_REST_DAYS_DEFAULT = 5.0
_REST_DAYS_CAP = 30.0

# MLB schedule abbreviations → gametime tricodes
_MLB_API_TEAM_TO_CANON: dict[str, str] = {
    "AZ": "ARI",
    "ATL": "ATL",
    "BAL": "BAL",
    "BOS": "BOS",
    "CHC": "CHC",
    "CIN": "CIN",
    "CLE": "CLE",
    "COL": "COL",
    "CWS": "CHW",
    "DET": "DET",
    "HOU": "HOU",
    "KC": "KCR",
    "LAA": "LAA",
    "LAD": "LAD",
    "MIA": "MIA",
    "MIL": "MIL",
    "MIN": "MIN",
    "NYM": "NYM",
    "NYY": "NYY",
    "OAK": "OAK",
    "ATH": "OAK",  # relocation alias
    "PHI": "PHI",
    "PIT": "PIT",
    "SD": "SDP",
    "SEA": "SEA",
    "SF": "SFG",
    "STL": "STL",
    "TB": "TBR",
    "TEX": "TEX",
    "TOR": "TOR",
    "WSH": "WSN",
}

_PITCHER_GAMES_COLUMNS = [
    "game_id",
    "home_sp_id",
    "away_sp_id",
    "home_sp_fip",
    "away_sp_fip",
    "home_sp_rest_days",
    "away_sp_rest_days",
    "has_starting_pitcher",
]


def _canon_from_mlb_api(abbrev: str) -> str:
    return _MLB_API_TEAM_TO_CANON.get(str(abbrev).strip().upper(), _norm_team(abbrev))


def _http_json(url: str, *, timeout: float = 30.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "gametime/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _compute_fip(ip: float, hr: float, bb: float, hbp: float, so: float) -> float:
    if ip <= 0:
        return LEAGUE_FIP
    return float((13 * hr + 3 * (bb + hbp) - 2 * so) / ip + FIP_CONSTANT)


class _PitcherCumStats:
    """Running counting stats for pre-game FIP (shifted prior)."""

    __slots__ = ("ip", "hr", "bb", "hbp", "so", "last_start")

    def __init__(self) -> None:
        self.ip = 0.0
        self.hr = 0.0
        self.bb = 0.0
        self.hbp = 0.0
        self.so = 0.0
        self.last_start: pd.Timestamp | None = None

    def fip_prior(self) -> float:
        if self.ip <= 0:
            return LEAGUE_FIP
        return _compute_fip(self.ip, self.hr, self.bb, self.hbp, self.so)

    def rest_days(self, game_date: pd.Timestamp) -> float:
        if self.last_start is None:
            return 5.0
        delta = (game_date.normalize() - self.last_start.normalize()).days
        return float(max(0, delta))

    def apply_game_line(
        self,
        *,
        ip: float,
        hr: float,
        bb: float,
        hbp: float,
        so: float,
        game_date: pd.Timestamp,
    ) -> None:
        self.ip += ip
        self.hr += hr
        self.bb += bb
        self.hbp += hbp
        self.so += so
        self.last_start = game_date.normalize()


def _parse_ip(ip_val: Any) -> float:
    if ip_val is None or (isinstance(ip_val, float) and pd.isna(ip_val)):
        return 0.0
    text = str(ip_val).strip()
    if not text or text == "0":
        return 0.0
    if "." in text:
        whole, frac = text.split(".", 1)
        return float(whole) + float(frac) / 3.0
    return float(text)


def _starter_from_boxscore(box: dict[str, Any], side: str) -> tuple[Optional[int], dict[str, float]]:
    players = box["teams"][side]["players"]
    for _pid, pdata in players.items():
        pit = pdata.get("stats", {}).get("pitching") or {}
        if pit.get("gamesStarted") == 1:
            pid = int(pdata["person"]["id"])
            line = {
                "ip": _parse_ip(pit.get("inningsPitched")),
                "hr": float(pit.get("homeRuns", 0) or 0),
                "bb": float(pit.get("baseOnBalls", 0) or 0),
                "hbp": float(pit.get("hitByPitch", 0) or 0),
                "so": float(pit.get("strikeOuts", 0) or 0),
            }
            return pid, line
    return None, {}


def fetch_boxscore_starters(game_pk: int) -> tuple[Optional[int], Optional[int], dict, dict]:
    """Return (home_sp_id, away_sp_id, home_line, away_line) from a completed game."""
    url = f"{MLB_STATS_BASE}/game/{game_pk}/boxscore"
    box = _http_json(url)
    home_id, home_line = _starter_from_boxscore(box, "home")
    away_id, away_line = _starter_from_boxscore(box, "away")
    return home_id, away_id, home_line, away_line


def fetch_schedule_games(game_date: date) -> list[dict[str, Any]]:
    url = (
        f"{MLB_STATS_BASE}/schedule?sportId=1&date={game_date.isoformat()}"
        "&gameType=R&hydrate=team"
    )
    payload = _http_json(url)
    rows: list[dict[str, Any]] = []
    for day in payload.get("dates", []):
        for g in day.get("games", []):
            if g.get("status", {}).get("abstractGameState") != "Final":
                continue
            home_abbr = g["teams"]["home"]["team"].get("abbreviation") or ""
            away_abbr = g["teams"]["away"]["team"].get("abbreviation") or ""
            rows.append(
                {
                    "game_pk": int(g["gamePk"]),
                    "game_date": pd.Timestamp(game_date).normalize(),
                    "home_team": _canon_from_mlb_api(home_abbr),
                    "away_team": _canon_from_mlb_api(away_abbr),
                }
            )
    return rows


def fetch_probable_pitchers(
    game_date: date,
    home: str,
    away: str,
) -> tuple[Optional[int], Optional[int]]:
    """Probable starters for an upcoming game (pregame inference)."""
    url = (
        f"{MLB_STATS_BASE}/schedule?sportId=1&date={game_date.isoformat()}"
        "&gameType=R&hydrate=probablePitcher"
    )
    payload = _http_json(url)
    home, away = home.upper(), away.upper()
    for day in payload.get("dates", []):
        for g in day.get("games", []):
            h = _canon_from_mlb_api(
                g["teams"]["home"]["team"].get("abbreviation", "")
            )
            a = _canon_from_mlb_api(
                g["teams"]["away"]["team"].get("abbreviation", "")
            )
            if h == home and a == away:
                home_pp = g["teams"]["home"].get("probablePitcher") or {}
                away_pp = g["teams"]["away"].get("probablePitcher") or {}
                hid = home_pp.get("id")
                aid = away_pp.get("id")
                return (
                    int(hid) if hid is not None else None,
                    int(aid) if aid is not None else None,
                )
    return None, None


def _cache_path(cache_dir: Path, game_pk: int) -> Path:
    return cache_dir / f"boxscore_{game_pk}.json"


def _load_cached_boxscore(cache_dir: Path, game_pk: int) -> Optional[dict[str, Any]]:
    path = _cache_path(cache_dir, game_pk)
    if not path.exists():
        return None
    with path.open() as f:
        return json.load(f)


def _save_cached_boxscore(cache_dir: Path, game_pk: int, box: dict[str, Any]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    with _cache_path(cache_dir, game_pk).open("w") as f:
        json.dump(box, f)


def _starters_from_cached_box(box: dict[str, Any]) -> tuple[Optional[int], Optional[int], dict, dict]:
    home_id, home_line = _starter_from_boxscore(box, "home")
    away_id, away_line = _starter_from_boxscore(box, "away")
    return home_id, away_id, home_line, away_line


def build_pitcher_games_table(
    games: pd.DataFrame,
    *,
    min_season: int = 2024,
    cache_dir: Optional[Path] = None,
    pause: float = 0.12,
    max_dates: Optional[int] = None,
) -> pd.DataFrame:
    """Build per-game starting-pitcher sidecar aligned to games.parquet game_id."""
    if games.empty:
        return pd.DataFrame(columns=_PITCHER_GAMES_COLUMNS)

    games = games.sort_values("game_date").reset_index(drop=True)
    sub = games[games["season_start_year"] >= min_season].copy()
    if sub.empty:
        return pd.DataFrame(columns=_PITCHER_GAMES_COLUMNS)

    cache_dir = cache_dir or Path("data/mlb/raw/pitcher_boxscores")
    cum: dict[int, _PitcherCumStats] = {}
    rows: list[dict[str, Any]] = []

    # Index games by (date, home, away) for matching schedule
    sub["game_date"] = pd.to_datetime(sub["game_date"]).dt.normalize()
    lookup: dict[tuple[pd.Timestamp, str, str], str] = {}
    for _, row in sub.iterrows():
        key = (row["game_date"], str(row["home_team"]), str(row["away_team"]))
        lookup[key] = str(row["game_id"])

    unique_dates = sorted(sub["game_date"].unique())
    if max_dates is not None:
        unique_dates = unique_dates[:max_dates]

    for game_date in unique_dates:
        day = game_date.date() if hasattr(game_date, "date") else pd.Timestamp(game_date).date()
        try:
            scheduled = fetch_schedule_games(day)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"[mlb-pitcher] schedule skip {day}: {exc}")
            time.sleep(pause)
            continue
        time.sleep(pause)

        for sched in scheduled:
            key = (sched["game_date"], sched["home_team"], sched["away_team"])
            game_id = lookup.get(key)
            if game_id is None:
                continue

            game_pk = int(sched["game_pk"])
            cached = _load_cached_boxscore(cache_dir, game_pk)
            if cached is None:
                try:
                    url = f"{MLB_STATS_BASE}/game/{game_pk}/boxscore"
                    cached = _http_json(url)
                    _save_cached_boxscore(cache_dir, game_pk, cached)
                except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                    print(f"[mlb-pitcher] boxscore skip {game_pk}: {exc}")
                    time.sleep(pause)
                    continue
                time.sleep(pause)

            home_id, away_id, home_line, away_line = _starters_from_cached_box(cached)
            if home_id is None or away_id is None:
                continue

            home_cum = cum.setdefault(home_id, _PitcherCumStats())
            away_cum = cum.setdefault(away_id, _PitcherCumStats())

            rows.append(
                {
                    "game_id": game_id,
                    "home_sp_id": home_id,
                    "away_sp_id": away_id,
                    "home_sp_fip": home_cum.fip_prior(),
                    "away_sp_fip": away_cum.fip_prior(),
                    "home_sp_rest_days": home_cum.rest_days(sched["game_date"]),
                    "away_sp_rest_days": away_cum.rest_days(sched["game_date"]),
                    "has_starting_pitcher": 1,
                }
            )

            if home_line:
                home_cum.apply_game_line(
                    ip=home_line["ip"],
                    hr=home_line["hr"],
                    bb=home_line["bb"],
                    hbp=home_line["hbp"],
                    so=home_line["so"],
                    game_date=sched["game_date"],
                )
            if away_line:
                away_cum.apply_game_line(
                    ip=away_line["ip"],
                    hr=away_line["hr"],
                    bb=away_line["bb"],
                    hbp=away_line["hbp"],
                    so=away_line["so"],
                    game_date=sched["game_date"],
                )

    if not rows:
        return pd.DataFrame(columns=_PITCHER_GAMES_COLUMNS)
    out = pd.DataFrame(rows).drop_duplicates("game_id")
    return out


def download_pitcher_games(
    games_path: Path,
    out_path: Path,
    *,
    min_season: int = 2024,
    cache_dir: Optional[Path] = None,
    pause: float = 0.12,
) -> Path:
    """Build or refresh pitcher sidecar from games.parquet."""
    games = pd.read_parquet(games_path)
    table = build_pitcher_games_table(
        games,
        min_season=min_season,
        cache_dir=cache_dir,
        pause=pause,
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(out_path, index=False)
    n = int((table.get("has_starting_pitcher", pd.Series(dtype=int)) == 1).sum())
    print(f"[mlb-pitcher] Wrote {len(table)} rows ({n} with SP) → {out_path}")
    return out_path


def load_pitcher_games(path: Path | None) -> pd.DataFrame:
    if path is None or not Path(path).exists():
        return pd.DataFrame(columns=_PITCHER_GAMES_COLUMNS)
    df = pd.read_parquet(path)
    for col in _PITCHER_GAMES_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    return df


def fip_prior_for_pitcher_id(
    pitcher_games: pd.DataFrame,
    games: pd.DataFrame,
    player_id: int,
    as_of_date: date,
) -> tuple[float, float]:
    """Last sidecar pre-game FIP and rest days for a pitcher strictly before ``as_of_date``."""
    if pitcher_games.empty or games.empty:
        return LEAGUE_FIP, _REST_DAYS_DEFAULT

    merged = pitcher_games.merge(
        games[["game_id", "game_date"]], on="game_id", how="inner"
    )
    if merged.empty:
        return LEAGUE_FIP, _REST_DAYS_DEFAULT

    merged["game_date"] = pd.to_datetime(merged["game_date"]).dt.normalize()
    as_of = pd.Timestamp(as_of_date).normalize()
    prior = merged[merged["game_date"] < as_of]
    if prior.empty:
        return LEAGUE_FIP, _REST_DAYS_DEFAULT

    pid = int(player_id)
    home_rows = prior[prior["home_sp_id"].notna() & (prior["home_sp_id"].astype(int) == pid)]
    away_rows = prior[prior["away_sp_id"].notna() & (prior["away_sp_id"].astype(int) == pid)]

    appearances: list[pd.DataFrame] = []
    if not home_rows.empty:
        appearances.append(
            home_rows[["game_date", "home_sp_fip"]].rename(columns={"home_sp_fip": "sp_fip"})
        )
    if not away_rows.empty:
        appearances.append(
            away_rows[["game_date", "away_sp_fip"]].rename(columns={"away_sp_fip": "sp_fip"})
        )
    if not appearances:
        return LEAGUE_FIP, _REST_DAYS_DEFAULT

    hist = pd.concat(appearances, ignore_index=True).sort_values("game_date")
    latest = hist.iloc[-1]
    fip = float(latest["sp_fip"]) if pd.notna(latest["sp_fip"]) else LEAGUE_FIP
    last_date = latest["game_date"].date()
    rest = float(max(0, min((as_of_date - last_date).days, _REST_DAYS_CAP)))
    return fip, rest
