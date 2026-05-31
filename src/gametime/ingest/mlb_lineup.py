"""Lineup strength sidecar for MLB pregame (M4 / W6k).

Sources (v1):
  - **Game lineup wOBA** (2024+): MLB Stats API boxscore batting order + player
    cumulative wOBA from prior plate appearances (no same-game lines).
  - **Team offense proxy** (fallback / older seasons): shifted rolling team
    ``runs_for`` scaled to wOBA units (games.parquet only).
  - **Optional enrich**: pybaseball ``team_batting`` / ``batting_stats`` when available.

``has_lineup=1`` when a confirmed batting order (5+ starters) is parsed from boxscore.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from gametime.ingest.mlb_pitchers import (
    MLB_STATS_BASE,
    _http_json,
    _load_cached_boxscore,
    _save_cached_boxscore,
    fetch_schedule_games,
)

LEAGUE_WOBA = 0.320
LEAGUE_RPG = 4.5

LINEUP_COLUMNS = [
    "game_id",
    "home_lineup_woba",
    "away_lineup_woba",
    "lineup_platoon_diff",
    "has_lineup",
]

_FG_TEAM_TO_CANON: dict[str, str] = {
    "ARI": "ARI",
    "ATL": "ATL",
    "BAL": "BAL",
    "BOS": "BOS",
    "CHC": "CHC",
    "CHW": "CHW",
    "CIN": "CIN",
    "CLE": "CLE",
    "COL": "COL",
    "DET": "DET",
    "HOU": "HOU",
    "KCR": "KCR",
    "KC": "KCR",
    "LAA": "LAA",
    "LAD": "LAD",
    "MIA": "MIA",
    "MIL": "MIL",
    "MIN": "MIN",
    "NYM": "NYM",
    "NYY": "NYY",
    "OAK": "OAK",
    "ATH": "OAK",
    "PHI": "PHI",
    "PIT": "PIT",
    "SDP": "SDP",
    "SD": "SDP",
    "SEA": "SEA",
    "SFG": "SFG",
    "SF": "SFG",
    "STL": "STL",
    "TBR": "TBR",
    "TB": "TBR",
    "TEX": "TEX",
    "TOR": "TOR",
    "WSN": "WSN",
    "WSH": "WSN",
}


def _canon_team(code: str) -> str:
    return _FG_TEAM_TO_CANON.get(str(code).strip().upper(), str(code).strip().upper())


class _PlayerBatCum:
    """Running PA components for pre-game wOBA (shifted prior)."""

    __slots__ = ("pa", "single", "double", "triple", "hr", "bb", "hbp")

    def __init__(self) -> None:
        self.pa = 0
        self.single = 0
        self.double = 0
        self.triple = 0
        self.hr = 0
        self.bb = 0
        self.hbp = 0

    def woba_prior(self) -> float:
        if self.pa <= 0:
            return LEAGUE_WOBA
        num = (
            0.69 * self.bb
            + 0.72 * self.hbp
            + 0.89 * self.single
            + 1.27 * self.double
            + 1.62 * self.triple
            + 2.10 * self.hr
        )
        return float(num / self.pa)

    def apply_batting_line(self, bat: dict[str, Any]) -> None:
        ab = int(bat.get("atBats") or 0)
        hits = int(bat.get("hits") or 0)
        doubles = int(bat.get("doubles") or 0)
        triples = int(bat.get("triples") or 0)
        hr = int(bat.get("homeRuns") or 0)
        bb = int(bat.get("baseOnBalls") or 0)
        hbp = int(bat.get("hitByPitch") or 0)
        sf = int(bat.get("sacFlies") or 0)
        pa = ab + bb + hbp + sf
        if pa <= 0:
            return
        singles = max(0, hits - doubles - triples - hr)
        self.pa += pa
        self.single += singles
        self.double += doubles
        self.triple += triples
        self.hr += hr
        self.bb += bb
        self.hbp += hbp


def _starter_batters(box: dict[str, Any], side: str) -> list[tuple[int, dict[str, Any]]]:
    players = box["teams"][side]["players"]
    starters: list[tuple[int, dict[str, Any]]] = []
    for pdata in players.values():
        bat = pdata.get("stats", {}).get("batting") or {}
        if not bat:
            continue
        order = pdata.get("battingOrder")
        if order is None:
            continue
        order_s = str(order)
        if not order_s or order_s[0] not in "123456789":
            continue
        pid = pdata.get("person", {}).get("id")
        if pid is None:
            continue
        starters.append((int(pid), bat))
    return starters


def _side_lineup_woba_prior(
    box: dict[str, Any],
    side: str,
    cum: dict[int, _PlayerBatCum],
) -> Optional[float]:
    values = [
        cum.setdefault(pid, _PlayerBatCum()).woba_prior()
        for pid, _ in _starter_batters(box, side)
    ]
    if len(values) >= 5:
        return float(np.mean(values))
    return None


def _apply_box_to_cum(box: dict[str, Any], cum: dict[int, _PlayerBatCum]) -> None:
    for side in ("home", "away"):
        for pid, bat in _starter_batters(box, side):
            cum.setdefault(pid, _PlayerBatCum()).apply_batting_line(bat)


def _team_woba_proxy_table(games: pd.DataFrame, *, window: int = 30) -> pd.DataFrame:
    """Per-game team offense wOBA proxy from prior runs only (no boxscore)."""
    g = games.sort_values("game_date").reset_index(drop=True)
    home = g.assign(
        team=g["home_team"],
        runs_for=g["home_runs"],
        game_id=g["game_id"],
    )[["game_id", "game_date", "team", "runs_for", "season_start_year"]]
    away = g.assign(
        team=g["away_team"],
        runs_for=g["away_runs"],
        game_id=g["game_id"],
    )[["game_id", "game_date", "team", "runs_for", "season_start_year"]]
    tg = pd.concat([home, away], ignore_index=True).sort_values(["team", "game_date"])
    min_p = max(3, window // 6)
    tg["rs_prior"] = tg.groupby("team", sort=False)["runs_for"].transform(
        lambda s: s.shift(1).rolling(window, min_periods=min_p).mean()
    )
    tg["team_woba_proxy"] = (tg["rs_prior"] / LEAGUE_RPG * LEAGUE_WOBA).fillna(LEAGUE_WOBA)

    home_map = g[["game_id", "home_team"]].rename(columns={"home_team": "team"})
    away_map = g[["game_id", "away_team"]].rename(columns={"away_team": "team"})
    tg_key = tg[["game_id", "team", "team_woba_proxy"]]
    home_proxy = home_map.merge(tg_key, on=["game_id", "team"], how="left")[
        ["game_id", "team_woba_proxy"]
    ].rename(columns={"team_woba_proxy": "home_lineup_woba"})
    away_proxy = away_map.merge(tg_key, on=["game_id", "team"], how="left")[
        ["game_id", "team_woba_proxy"]
    ].rename(columns={"team_woba_proxy": "away_lineup_woba"})
    return home_proxy.merge(away_proxy, on="game_id", how="outer")


def _load_team_woba_season(season: int, cache_dir: Path) -> dict[str, float]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"team_woba_{season}.json"
    if path.exists():
        with path.open() as f:
            raw = json.load(f)
        return {str(k).upper(): float(v) for k, v in raw.items()}

    team_woba: dict[str, float] = {}
    try:
        from pybaseball import team_batting

        df = team_batting(season)
        if df is not None and not df.empty and "wOBA" in df.columns:
            team_col = "Team" if "Team" in df.columns else "team"
            for _, row in df.iterrows():
                tri = _canon_team(row[team_col])
                woba = row.get("wOBA")
                if pd.notna(woba):
                    team_woba[tri] = float(woba)
    except Exception as exc:  # noqa: BLE001
        print(f"[mlb-lineup] team_batting({season}) skip: {exc}")

    with path.open("w") as f:
        json.dump(team_woba, f)
    return team_woba


def build_lineup_games_table(
    games: pd.DataFrame,
    *,
    min_season: int = 2024,
    cache_dir: Optional[Path] = None,
    boxscore_cache_dir: Optional[Path] = None,
    pause: float = 0.12,
    max_dates: Optional[int] = None,
) -> pd.DataFrame:
    """Build per-game lineup sidecar aligned to games.parquet ``game_id``."""
    if games.empty:
        return pd.DataFrame(columns=LINEUP_COLUMNS)

    games = games.sort_values("game_date").reset_index(drop=True)
    cache_dir = cache_dir or Path("data/mlb/raw/lineup_woba")
    boxscore_cache_dir = boxscore_cache_dir or Path("data/mlb/raw/pitcher_boxscores")
    proxy = _team_woba_proxy_table(games)

    lineup_by_game: dict[str, dict[str, Any]] = {}
    cum: dict[int, _PlayerBatCum] = {}

    sub = games[games["season_start_year"] >= min_season].copy()
    if not sub.empty:
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
            except Exception as exc:  # noqa: BLE001
                print(f"[mlb-lineup] schedule skip {day}: {exc}")
                time.sleep(pause)
                continue
            time.sleep(pause)

            for sched in scheduled:
                key = (sched["game_date"], sched["home_team"], sched["away_team"])
                game_id = lookup.get(key)
                if game_id is None:
                    continue
                game_pk = int(sched["game_pk"])
                cached = _load_cached_boxscore(boxscore_cache_dir, game_pk)
                if cached is None:
                    try:
                        url = f"{MLB_STATS_BASE}/game/{game_pk}/boxscore"
                        cached = _http_json(url)
                        _save_cached_boxscore(boxscore_cache_dir, game_pk, cached)
                    except Exception as exc:  # noqa: BLE001
                        print(f"[mlb-lineup] boxscore skip {game_pk}: {exc}")
                        time.sleep(pause)
                        continue
                    time.sleep(pause)

                home_lu = _side_lineup_woba_prior(cached, "home", cum)
                away_lu = _side_lineup_woba_prior(cached, "away", cum)
                if home_lu is not None and away_lu is not None:
                    lineup_by_game[game_id] = {
                        "game_id": game_id,
                        "home_lineup_woba": home_lu,
                        "away_lineup_woba": away_lu,
                        "lineup_platoon_diff": home_lu - away_lu,
                        "has_lineup": 1,
                    }
                _apply_box_to_cum(cached, cum)

    rows: list[dict[str, Any]] = []
    proxy_idx = proxy.set_index("game_id")
    for _, row in games.iterrows():
        game_id = str(row["game_id"])
        if game_id in lineup_by_game:
            rows.append(lineup_by_game[game_id])
            continue
        home_w = away_w = LEAGUE_WOBA
        if game_id in proxy_idx.index:
            prow = proxy_idx.loc[game_id]
            home_w = float(prow["home_lineup_woba"])
            away_w = float(prow["away_lineup_woba"])
        rows.append(
            {
                "game_id": game_id,
                "home_lineup_woba": home_w,
                "away_lineup_woba": away_w,
                "lineup_platoon_diff": home_w - away_w,
                "has_lineup": 0,
            }
        )

    return pd.DataFrame(rows, columns=LINEUP_COLUMNS)


def download_lineup_games(
    games_path: Path,
    out_path: Path,
    *,
    min_season: int = 2024,
    cache_dir: Optional[Path] = None,
    boxscore_cache_dir: Optional[Path] = None,
    pause: float = 0.12,
    max_dates: Optional[int] = None,
) -> Path:
    games = pd.read_parquet(games_path)
    table = build_lineup_games_table(
        games,
        min_season=min_season,
        cache_dir=cache_dir,
        boxscore_cache_dir=boxscore_cache_dir,
        pause=pause,
        max_dates=max_dates,
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(out_path, index=False)
    n = int((table.get("has_lineup", pd.Series(dtype=int)) == 1).sum())
    print(f"[mlb-lineup] Wrote {len(table)} rows ({n} with lineup) → {out_path}")
    return out_path


def load_lineup_games(path: Path | None) -> pd.DataFrame:
    if path is None or not Path(path).exists():
        return pd.DataFrame(columns=LINEUP_COLUMNS)
    df = pd.read_parquet(path)
    for col in LINEUP_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    return df[LINEUP_COLUMNS].copy()
