"""Statcast team offense sidecar for MLB pregame (W12 / P3).

Sources:
  - **pybaseball** ``statcast`` daily play-level pulls (cached per date).
  - Aggregated to **team-date** batting quality: xwOBA, barrel%, hard-hit%.
  - **shift(1)** then **30-day** rolling window on team-date series (no same-game leakage).

``has_statcast_offense=1`` when both teams have Statcast-backed rolling values
(min PA threshold in window); ``0`` with league-average fallbacks otherwise.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

LEAGUE_XWOBA = 0.320
LEAGUE_BARREL_PCT = 0.080
LEAGUE_HARD_HIT_PCT = 0.390
ROLL_WINDOW_DAYS = 30
MIN_ROLL_PA = 50

STATCAST_OFFENSE_COLUMNS = [
    "game_id",
    "home_xwoba_roll",
    "away_xwoba_roll",
    "home_barrel_pct_roll",
    "away_barrel_pct_roll",
    "home_hard_hit_pct_roll",
    "away_hard_hit_pct_roll",
    "xwoba_off_diff",
    "has_statcast_offense",
]

_TEAM_TO_CANON: dict[str, str] = {
    "ARI": "ARI", "AZ": "ARI", "ATL": "ATL", "BAL": "BAL", "BOS": "BOS",
    "CHC": "CHC", "CHW": "CHW", "CWS": "CHW", "CIN": "CIN", "CLE": "CLE",
    "COL": "COL", "DET": "DET", "HOU": "HOU", "KCR": "KCR", "KC": "KCR",
    "LAA": "LAA", "LAD": "LAD", "MIA": "MIA", "MIL": "MIL", "MIN": "MIN",
    "NYM": "NYM", "NYY": "NYY", "OAK": "OAK", "ATH": "OAK", "PHI": "PHI",
    "PIT": "PIT", "SDP": "SDP", "SD": "SDP", "SEA": "SEA", "SFG": "SFG",
    "SF": "SFG", "STL": "STL", "TBR": "TBR", "TB": "TBR", "TEX": "TEX",
    "TOR": "TOR", "WSN": "WSN", "WSH": "WSN",
}


def _canon_team(code: str) -> str:
    return _TEAM_TO_CANON.get(str(code).strip().upper(), str(code).strip().upper())


def _batting_team(home_team: str, away_team: str, inning_topbot: str) -> str:
    if str(inning_topbot).strip().lower().startswith("top"):
        return _canon_team(away_team)
    return _canon_team(home_team)


def _aggregate_day_statcast(raw: pd.DataFrame) -> pd.DataFrame:
    """Team-date batting aggregates from one day of Statcast pitch rows."""
    if raw.empty:
        return pd.DataFrame(
            columns=[
                "team", "game_date", "pa", "xwoba_num", "xwoba_den",
                "bbe", "barrels", "hard_hits",
            ]
        )

    df = raw.copy()
    df["game_date"] = pd.to_datetime(df["game_date"]).dt.normalize()
    df["team"] = [
        _batting_team(h, a, tb)
        for h, a, tb in zip(df["home_team"], df["away_team"], df["inning_topbot"])
    ]

    pa_mask = pd.to_numeric(df["woba_denom"], errors="coerce").fillna(0) > 0
    bbe_mask = pd.to_numeric(df["launch_speed"], errors="coerce").notna()
    launch_speed = pd.to_numeric(df["launch_speed"], errors="coerce")
    launch_speed_angle = pd.to_numeric(df["launch_speed_angle"], errors="coerce")

    df["xwoba_num"] = pd.to_numeric(df["woba_value"], errors="coerce").fillna(0.0)
    df["xwoba_den"] = pd.to_numeric(df["woba_denom"], errors="coerce").fillna(0.0)
    df["is_bbe"] = bbe_mask.fillna(False).astype(int)
    df["is_barrel"] = ((launch_speed_angle == 6) & bbe_mask).fillna(False).astype(int)
    df["is_hard_hit"] = ((launch_speed >= 95) & bbe_mask).fillna(False).astype(int)
    df["is_pa"] = pa_mask.fillna(False).astype(int)

    return (
        df.groupby(["team", "game_date"], as_index=False)
        .agg(
            pa=("is_pa", "sum"),
            xwoba_num=("xwoba_num", "sum"),
            xwoba_den=("xwoba_den", "sum"),
            bbe=("is_bbe", "sum"),
            barrels=("is_barrel", "sum"),
            hard_hits=("is_hard_hit", "sum"),
        )
        .sort_values(["team", "game_date"])
    )


def _daily_cache_path(cache_dir: Path, day: pd.Timestamp) -> Path:
    return cache_dir / f"team_daily_{pd.Timestamp(day).date().isoformat()}.parquet"


def _fetch_statcast_day(day: pd.Timestamp, *, pause: float) -> pd.DataFrame:
    from pybaseball import statcast

    ds = pd.Timestamp(day).date().isoformat()
    try:
        raw = statcast(ds, ds, verbose=False)
    except Exception as exc:  # noqa: BLE001
        print(f"[mlb-statcast-offense] statcast skip {ds}: {exc}")
        time.sleep(pause)
        return pd.DataFrame()
    time.sleep(pause)
    return _aggregate_day_statcast(raw)


def _fetch_statcast_range(
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    pause: float,
) -> pd.DataFrame:
    from pybaseball import statcast

    ds = pd.Timestamp(start).date().isoformat()
    de = pd.Timestamp(end).date().isoformat()
    try:
        raw = statcast(ds, de, verbose=False)
    except Exception as exc:  # noqa: BLE001
        print(f"[mlb-statcast-offense] statcast skip {ds}..{de}: {exc}")
        time.sleep(pause)
        return pd.DataFrame()
    time.sleep(pause)
    if raw.empty:
        return pd.DataFrame()
    raw["game_date"] = pd.to_datetime(raw["game_date"]).dt.normalize()
    frames = [_aggregate_day_statcast(sub) for _, sub in raw.groupby("game_date")]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _ensure_daily_caches(
    unique_dates: list[pd.Timestamp],
    *,
    cache_dir: Path,
    pause: float,
    chunk_days: int = 7,
) -> None:
    """Fetch and cache missing daily team aggregates (batched Statcast pulls)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    missing = [
        pd.Timestamp(d).normalize()
        for d in unique_dates
        if not _daily_cache_path(cache_dir, d).exists()
    ]
    if not missing:
        return
    missing = sorted(set(missing))
    i = 0
    while i < len(missing):
        start = missing[i]
        end = start
        j = i + 1
        while j < len(missing):
            nxt = missing[j]
            if (nxt - end).days <= chunk_days and (nxt - start).days <= chunk_days:
                end = nxt
                j += 1
            else:
                break
        agg = _fetch_statcast_range(start, end, pause=pause)
        if not agg.empty:
            for gdate, sub in agg.groupby("game_date"):
                sub.to_parquet(_daily_cache_path(cache_dir, gdate), index=False)
        cur = start
        while cur <= end:
            path = _daily_cache_path(cache_dir, cur)
            if not path.exists():
                pd.DataFrame(
                    columns=[
                        "team", "game_date", "pa", "xwoba_num", "xwoba_den",
                        "bbe", "barrels", "hard_hits",
                    ]
                ).to_parquet(path, index=False)
            cur = cur + pd.Timedelta(days=1)
        if (i // chunk_days) % 10 == 0:
            print(f"[mlb-statcast-offense] cached through {end.date()} ({j}/{len(missing)} days)")
        i = j


def _team_rolling_metrics(
    daily: pd.DataFrame,
    *,
    window: int = ROLL_WINDOW_DAYS,
    min_pa: int = MIN_ROLL_PA,
) -> pd.DataFrame:
    """shift(1) rolling team-date offense quality (no same-day leakage)."""
    if daily.empty:
        return pd.DataFrame(
            columns=[
                "team", "game_date", "xwoba_roll", "barrel_pct_roll",
                "hard_hit_pct_roll", "has_statcast",
            ]
        )

    tg = daily.sort_values(["team", "game_date"]).reset_index(drop=True)
    g = tg.groupby("team", sort=False)
    min_periods = max(3, window // 6)

    for col in ("pa", "xwoba_num", "xwoba_den", "bbe", "barrels", "hard_hits"):
        tg[f"prior_{col}"] = g[col].transform(lambda s: s.shift(1))

    tg["roll_pa"] = g["prior_pa"].transform(
        lambda s: s.rolling(window, min_periods=min_periods).sum()
    )
    tg["roll_xwoba_num"] = g["prior_xwoba_num"].transform(
        lambda s: s.rolling(window, min_periods=min_periods).sum()
    )
    tg["roll_xwoba_den"] = g["prior_xwoba_den"].transform(
        lambda s: s.rolling(window, min_periods=min_periods).sum()
    )
    tg["roll_bbe"] = g["prior_bbe"].transform(
        lambda s: s.rolling(window, min_periods=min_periods).sum()
    )
    tg["roll_barrels"] = g["prior_barrels"].transform(
        lambda s: s.rolling(window, min_periods=min_periods).sum()
    )
    tg["roll_hard_hits"] = g["prior_hard_hits"].transform(
        lambda s: s.rolling(window, min_periods=min_periods).sum()
    )

    tg["xwoba_roll"] = np.where(
        tg["roll_xwoba_den"] > 0,
        tg["roll_xwoba_num"] / tg["roll_xwoba_den"],
        LEAGUE_XWOBA,
    )
    tg["barrel_pct_roll"] = np.where(
        tg["roll_bbe"] > 0,
        tg["roll_barrels"] / tg["roll_bbe"],
        LEAGUE_BARREL_PCT,
    )
    tg["hard_hit_pct_roll"] = np.where(
        tg["roll_bbe"] > 0,
        tg["roll_hard_hits"] / tg["roll_bbe"],
        LEAGUE_HARD_HIT_PCT,
    )
    tg["has_statcast"] = (tg["roll_pa"] >= min_pa).astype(int)
    return tg[
        [
            "team", "game_date", "xwoba_roll", "barrel_pct_roll",
            "hard_hit_pct_roll", "has_statcast",
        ]
    ]


def build_statcast_offense_games_table(
    games: pd.DataFrame,
    *,
    min_season: int = 2021,
    cache_dir: Optional[Path] = None,
    pause: float = 0.35,
    max_dates: Optional[int] = None,
    roll_window: int = ROLL_WINDOW_DAYS,
    min_roll_pa: int = MIN_ROLL_PA,
) -> pd.DataFrame:
    """Build per-game Statcast offense sidecar aligned to games.parquet ``game_id``."""
    if games.empty:
        return pd.DataFrame(columns=STATCAST_OFFENSE_COLUMNS)

    games = games.sort_values("game_date").reset_index(drop=True)
    cache_dir = cache_dir or Path("data/mlb/raw/statcast_offense")

    sub = games[games["season_start_year"] >= min_season].copy()
    sub["game_date"] = pd.to_datetime(sub["game_date"]).dt.normalize()
    unique_dates = sorted(sub["game_date"].unique())
    if max_dates is not None:
        unique_dates = unique_dates[:max_dates]

    daily_frames: list[pd.DataFrame] = []
    _ensure_daily_caches(unique_dates, cache_dir=cache_dir, pause=pause)
    for game_date in unique_dates:
        path = _daily_cache_path(cache_dir, game_date)
        if path.exists():
            frame = pd.read_parquet(path)
            if not frame.empty:
                daily_frames.append(frame)

    if daily_frames:
        daily = (
            pd.concat(daily_frames, ignore_index=True)
            .groupby(["team", "game_date"], as_index=False)
            .agg(
                pa=("pa", "sum"),
                xwoba_num=("xwoba_num", "sum"),
                xwoba_den=("xwoba_den", "sum"),
                bbe=("bbe", "sum"),
                barrels=("barrels", "sum"),
                hard_hits=("hard_hits", "sum"),
            )
            .sort_values(["team", "game_date"])
        )
    else:
        daily = pd.DataFrame(
            columns=["team", "game_date", "pa", "xwoba_num", "xwoba_den", "bbe", "barrels", "hard_hits"]
        )

    team_roll = _team_rolling_metrics(daily, window=roll_window, min_pa=min_roll_pa)
    roll_idx = team_roll.set_index(["team", "game_date"])

    rows: list[dict[str, Any]] = []
    for _, row in games.iterrows():
        game_id = str(row["game_id"])
        gdate = pd.to_datetime(row["game_date"]).normalize()
        home = _canon_team(row["home_team"])
        away = _canon_team(row["away_team"])

        def _side(team: str) -> tuple[float, float, float, int]:
            key = (team, gdate)
            if key not in roll_idx.index:
                return LEAGUE_XWOBA, LEAGUE_BARREL_PCT, LEAGUE_HARD_HIT_PCT, 0
            srow = roll_idx.loc[key]
            if isinstance(srow, pd.DataFrame):
                srow = srow.iloc[-1]
            has = int(srow.get("has_statcast", 0))
            if has != 1:
                return LEAGUE_XWOBA, LEAGUE_BARREL_PCT, LEAGUE_HARD_HIT_PCT, 0
            return (
                float(srow["xwoba_roll"]),
                float(srow["barrel_pct_roll"]),
                float(srow["hard_hit_pct_roll"]),
                1,
            )

        home_x, home_b, home_h, home_has = _side(home)
        away_x, away_b, away_h, away_has = _side(away)
        has_statcast = 1 if (home_has == 1 and away_has == 1) else 0
        rows.append(
            {
                "game_id": game_id,
                "home_xwoba_roll": home_x,
                "away_xwoba_roll": away_x,
                "home_barrel_pct_roll": home_b,
                "away_barrel_pct_roll": away_b,
                "home_hard_hit_pct_roll": home_h,
                "away_hard_hit_pct_roll": away_h,
                "xwoba_off_diff": home_x - away_x,
                "has_statcast_offense": has_statcast,
            }
        )

    return pd.DataFrame(rows, columns=STATCAST_OFFENSE_COLUMNS)


def download_statcast_offense_games(
    games_path: Path,
    out_path: Path,
    *,
    min_season: int = 2021,
    cache_dir: Optional[Path] = None,
    pause: float = 0.35,
    max_dates: Optional[int] = None,
    roll_window: int = ROLL_WINDOW_DAYS,
    min_roll_pa: int = MIN_ROLL_PA,
) -> Path:
    games = pd.read_parquet(games_path)
    table = build_statcast_offense_games_table(
        games,
        min_season=min_season,
        cache_dir=cache_dir,
        pause=pause,
        max_dates=max_dates,
        roll_window=roll_window,
        min_roll_pa=min_roll_pa,
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(out_path, index=False)
    n = int((table.get("has_statcast_offense", pd.Series(dtype=int)) == 1).sum())
    print(f"[mlb-statcast-offense] Wrote {len(table)} rows ({n} with statcast) → {out_path}")
    return out_path


def load_statcast_offense_games(path: Path | None) -> pd.DataFrame:
    if path is None or not Path(path).exists():
        return pd.DataFrame(columns=STATCAST_OFFENSE_COLUMNS)
    df = pd.read_parquet(path)
    for col in STATCAST_OFFENSE_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    return df[STATCAST_OFFENSE_COLUMNS].copy()
