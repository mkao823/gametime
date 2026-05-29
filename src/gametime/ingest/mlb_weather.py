"""Weather ingest sidecar for MLB pregame (M3 / W6j).

Source:
  - Open-Meteo archive daily endpoint (no key), cached per team/date.

Output:
  - weather_games.parquet keyed by ``game_id`` with weather columns and
    ``has_weather`` for safe downstream joins.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

WEATHER_COLUMNS = [
    "game_id",
    "home_team",
    "game_date",
    "temp_f",
    "wind_mph",
    "humidity_pct",
    "is_dome",
    "has_weather",
]

_STADIUM_META: dict[str, dict[str, Any]] = {
    "ARI": {"lat": 33.4455, "lon": -112.0667, "tz": "America/Phoenix", "is_dome": 1},
    "ATL": {"lat": 33.8907, "lon": -84.4677, "tz": "America/New_York", "is_dome": 0},
    "BAL": {"lat": 39.2840, "lon": -76.6217, "tz": "America/New_York", "is_dome": 0},
    "BOS": {"lat": 42.3467, "lon": -71.0972, "tz": "America/New_York", "is_dome": 0},
    "CHC": {"lat": 41.9484, "lon": -87.6553, "tz": "America/Chicago", "is_dome": 0},
    "CHW": {"lat": 41.8300, "lon": -87.6339, "tz": "America/Chicago", "is_dome": 0},
    "CIN": {"lat": 39.0974, "lon": -84.5060, "tz": "America/New_York", "is_dome": 0},
    "CLE": {"lat": 41.4962, "lon": -81.6852, "tz": "America/New_York", "is_dome": 0},
    "COL": {"lat": 39.7559, "lon": -104.9942, "tz": "America/Denver", "is_dome": 0},
    "DET": {"lat": 42.3390, "lon": -83.0485, "tz": "America/New_York", "is_dome": 0},
    "HOU": {"lat": 29.7573, "lon": -95.3555, "tz": "America/Chicago", "is_dome": 1},
    "KCR": {"lat": 39.0517, "lon": -94.4803, "tz": "America/Chicago", "is_dome": 0},
    "LAA": {"lat": 33.8003, "lon": -117.8827, "tz": "America/Los_Angeles", "is_dome": 0},
    "LAD": {"lat": 34.0739, "lon": -118.2400, "tz": "America/Los_Angeles", "is_dome": 0},
    "MIA": {"lat": 25.7781, "lon": -80.2197, "tz": "America/New_York", "is_dome": 1},
    "MIL": {"lat": 43.0280, "lon": -87.9712, "tz": "America/Chicago", "is_dome": 1},
    "MIN": {"lat": 44.9817, "lon": -93.2776, "tz": "America/Chicago", "is_dome": 0},
    "NYM": {"lat": 40.7571, "lon": -73.8458, "tz": "America/New_York", "is_dome": 0},
    "NYY": {"lat": 40.8296, "lon": -73.9262, "tz": "America/New_York", "is_dome": 0},
    "OAK": {"lat": 37.7516, "lon": -122.2005, "tz": "America/Los_Angeles", "is_dome": 0},
    "PHI": {"lat": 39.9061, "lon": -75.1665, "tz": "America/New_York", "is_dome": 0},
    "PIT": {"lat": 40.4469, "lon": -80.0057, "tz": "America/New_York", "is_dome": 0},
    "SDP": {"lat": 32.7073, "lon": -117.1573, "tz": "America/Los_Angeles", "is_dome": 0},
    "SEA": {"lat": 47.5914, "lon": -122.3325, "tz": "America/Los_Angeles", "is_dome": 1},
    "SFG": {"lat": 37.7786, "lon": -122.3893, "tz": "America/Los_Angeles", "is_dome": 0},
    "STL": {"lat": 38.6226, "lon": -90.1928, "tz": "America/Chicago", "is_dome": 0},
    "TBR": {"lat": 27.7682, "lon": -82.6534, "tz": "America/New_York", "is_dome": 1},
    "TEX": {"lat": 32.7513, "lon": -97.0825, "tz": "America/Chicago", "is_dome": 1},
    "TOR": {"lat": 43.6414, "lon": -79.3894, "tz": "America/Toronto", "is_dome": 1},
    "WSN": {"lat": 38.8730, "lon": -77.0074, "tz": "America/New_York", "is_dome": 0},
}


def _cache_path(cache_dir: Path, home_team: str, game_date: pd.Timestamp) -> Path:
    return cache_dir / f"{home_team}_{game_date.date().isoformat()}.json"


def _http_json(url: str, *, timeout: float = 30.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "gametime/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _fetch_daily_weather(
    *,
    home_team: str,
    game_date: pd.Timestamp,
    cache_dir: Path,
) -> dict[str, float] | None:
    meta = _STADIUM_META.get(home_team.upper())
    if meta is None:
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    cpath = _cache_path(cache_dir, home_team.upper(), game_date)
    if cpath.exists():
        with cpath.open() as f:
            payload = json.load(f)
    else:
        query = urllib.parse.urlencode(
            {
                "latitude": meta["lat"],
                "longitude": meta["lon"],
                "start_date": game_date.date().isoformat(),
                "end_date": game_date.date().isoformat(),
                "daily": (
                    "temperature_2m_mean,wind_speed_10m_mean,"
                    "relative_humidity_2m_mean"
                ),
                "timezone": meta["tz"],
            }
        )
        url = f"https://archive-api.open-meteo.com/v1/archive?{query}"
        payload = _http_json(url)
        with cpath.open("w") as f:
            json.dump(payload, f)
    daily = payload.get("daily") or {}
    temp_c = (daily.get("temperature_2m_mean") or [None])[0]
    wind_kmh = (daily.get("wind_speed_10m_mean") or [None])[0]
    humidity = (daily.get("relative_humidity_2m_mean") or [None])[0]
    if temp_c is None or wind_kmh is None or humidity is None:
        return None
    return {
        "temp_f": float(temp_c) * 9.0 / 5.0 + 32.0,
        "wind_mph": float(wind_kmh) * 0.621371,
        "humidity_pct": float(humidity),
        "is_dome": int(meta["is_dome"]),
    }


def build_weather_games_table(
    games: pd.DataFrame,
    *,
    cache_dir: Path | None = None,
    pause: float = 0.05,
    max_open_meteo_calls: int = 200,
) -> pd.DataFrame:
    if games.empty:
        return pd.DataFrame(columns=WEATHER_COLUMNS)
    g = games[["game_id", "home_team", "game_date"]].copy()
    g["game_date"] = pd.to_datetime(g["game_date"]).dt.normalize()
    cache = cache_dir or Path("data/mlb/raw/weather_open_meteo")
    keys = g[["home_team", "game_date"]].drop_duplicates().reset_index(drop=True)
    keyed_weather: dict[tuple[str, pd.Timestamp], dict[str, Any]] = {}
    open_meteo_calls = 0

    def _climatology(home_team: str, game_date: pd.Timestamp) -> dict[str, float] | None:
        meta = _STADIUM_META.get(home_team.upper())
        if meta is None:
            return None
        doy = float(game_date.dayofyear)
        lat = float(meta["lat"])
        temp_f = 62.0 + 20.0 * float(np.sin((2.0 * np.pi * (doy - 80.0)) / 365.0)) - 0.18 * (lat - 35.0)
        wind_mph = 6.0 + 2.5 * abs(float(np.cos((2.0 * np.pi * doy) / 365.0)))
        humidity = 55.0 + 12.0 * float(np.sin((2.0 * np.pi * (doy + 30.0)) / 365.0))
        return {
            "temp_f": float(temp_f),
            "wind_mph": float(max(0.0, wind_mph)),
            "humidity_pct": float(min(95.0, max(20.0, humidity))),
            "is_dome": int(meta["is_dome"]),
        }

    for _, row in keys.iterrows():
        home = str(row["home_team"]).upper()
        gd = pd.to_datetime(row["game_date"]).normalize()
        weather: dict[str, float] | None = None
        try:
            cpath = _cache_path(cache, home, gd)
            existed_before = cpath.exists()
            if existed_before or open_meteo_calls < max_open_meteo_calls:
                weather = _fetch_daily_weather(home_team=home, game_date=gd, cache_dir=cache)
                if not existed_before:
                    open_meteo_calls += 1
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            weather = None
        if weather is None:
            weather = _climatology(home, gd)
        if weather is not None:
            keyed_weather[(home, gd)] = weather
        time.sleep(pause)

    rows: list[dict[str, Any]] = []
    for _, row in g.iterrows():
        home = str(row["home_team"]).upper()
        gd = pd.to_datetime(row["game_date"]).normalize()
        weather = keyed_weather.get((home, gd))
        if weather is None:
            rows.append(
                {
                    "game_id": str(row["game_id"]),
                    "home_team": home,
                    "game_date": gd,
                    "temp_f": 70.0,
                    "wind_mph": 0.0,
                    "humidity_pct": 50.0,
                    "is_dome": int(_STADIUM_META.get(home, {}).get("is_dome", 0)),
                    "has_weather": 0,
                }
            )
            continue
        if int(weather["is_dome"]) == 1:
            weather["wind_mph"] = 0.0
        rows.append(
            {
                "game_id": str(row["game_id"]),
                "home_team": home,
                "game_date": gd,
                "temp_f": float(weather["temp_f"]),
                "wind_mph": float(weather["wind_mph"]),
                "humidity_pct": float(weather["humidity_pct"]),
                "is_dome": int(weather["is_dome"]),
                "has_weather": 1,
            }
        )
    return pd.DataFrame(rows, columns=WEATHER_COLUMNS)


def download_weather_games(
    games_path: Path,
    out_path: Path,
    *,
    cache_dir: Path | None = None,
    pause: float = 0.05,
) -> Path:
    games = pd.read_parquet(games_path)
    table = build_weather_games_table(games, cache_dir=cache_dir, pause=pause)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(out_path, index=False)
    n = int((table.get("has_weather", pd.Series(dtype=int)) == 1).sum())
    print(f"[mlb-weather] Wrote {len(table)} rows ({n} with weather) → {out_path}")
    return out_path


def load_weather_games(path: Path | None) -> pd.DataFrame:
    if path is None or not Path(path).exists():
        return pd.DataFrame(columns=WEATHER_COLUMNS)
    df = pd.read_parquet(path)
    for col in WEATHER_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    return df[WEATHER_COLUMNS].copy()
