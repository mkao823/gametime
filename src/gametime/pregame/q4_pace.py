"""Regulation Q4 scoring totals from play-by-play (classic nbastats + v3)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import pandas as pd

from gametime.data.pbp import parse_score_pair

ISO_CLOCK = re.compile(
    r"^PT(?P<min>\d+)M(?P<sec>\d+(?:\.\d+)?)S$",
    re.IGNORECASE,
)

LEAGUE_Q4_PACE48 = 220.0  # typical extrapolated Q4 scoring pace


def _normalize_game_id(series: pd.Series) -> pd.Series:
    return series.astype(str).str.zfill(10)


def _q4_total_classic(raw: pd.DataFrame) -> float | None:
    df = raw.sort_values("EVENTNUM")
    scored = df[df["SCORE"].notna()].copy()
    if scored.empty:
        return None
    pairs = scored["SCORE"].map(parse_score_pair)
    valid = pairs.notna()
    scored = scored[valid].copy()
    pairs = pairs[valid]
    if scored.empty:
        return None
    scored["away_s"] = pairs.map(lambda t: t[0])
    scored["home_s"] = pairs.map(lambda t: t[1])
    scored["total_s"] = scored["away_s"] + scored["home_s"]
    scored["period"] = pd.to_numeric(scored["PERIOD"], errors="coerce")

    q3 = scored[scored["period"] <= 3]
    q4 = scored[scored["period"] == 4]
    if q4.empty:
        return None
    total_q3 = float(q3["total_s"].iloc[-1]) if not q3.empty else 0.0
    total_q4_end = float(q4["total_s"].iloc[-1])
    q4_total = total_q4_end - total_q3
    return max(0.0, q4_total)


def _q4_total_v3(raw: pd.DataFrame) -> float | None:
    df = raw.sort_values("actionNumber")
    scored = df.dropna(subset=["scoreHome", "scoreAway"]).copy()
    if scored.empty:
        return None
    scored["period"] = pd.to_numeric(scored["period"], errors="coerce")
    scored["total_s"] = scored["scoreHome"].astype(float) + scored["scoreAway"].astype(float)
    q3 = scored[scored["period"] <= 3]
    q4 = scored[scored["period"] == 4]
    if q4.empty:
        return None
    total_q3 = float(q3["total_s"].iloc[-1]) if not q3.empty else 0.0
    total_q4_end = float(q4["total_s"].iloc[-1])
    return max(0.0, total_q4_end - total_q3)


def q4_total_from_raw(raw: pd.DataFrame) -> float | None:
    if "SCORE" in raw.columns:
        return _q4_total_classic(raw)
    if "scoreHome" in raw.columns:
        return _q4_total_v3(raw)
    return None


def _iter_pbp_files(raw_dir: Path, seasons: Iterable[int], seasontype: str) -> list[Path]:
    paths = []
    types = ("rg", "po") if seasontype == "both" else (seasontype,)
    for st in types:
        for season in seasons:
            suffix = f"_{season}" if st == "rg" else f"_po_{season}"
            p = raw_dir / f"nbastats{suffix}.csv"
            if p.exists():
                paths.append(p)
    return paths


def build_q4_pace_table(
    raw_dir: Path,
    *,
    seasons: Iterable[int],
    seasontype: str = "both",
    v3_archive_seasons: Iterable[int] | None = None,
) -> pd.DataFrame:
    """One row per game: q4_total (regulation Q4 points) and q4_pace48."""
    rows: list[dict] = []
    usecols_classic = ["GAME_ID", "EVENTNUM", "PERIOD", "SCORE"]
    for path in _iter_pbp_files(raw_dir, seasons, seasontype):
        raw = pd.read_csv(path, usecols=usecols_classic, low_memory=False)
        for gid, grp in raw.groupby("GAME_ID"):
            q4 = q4_total_from_raw(grp)
            if q4 is not None:
                rows.append({"game_id": str(gid).zfill(10), "q4_total": q4, "q4_pace48": q4 * 4.0})

    if v3_archive_seasons:
        v3_cols = ["gameId", "actionNumber", "period", "scoreHome", "scoreAway"]
        for season in v3_archive_seasons:
            path = raw_dir / f"nbastatsv3_{season}.csv"
            if not path.exists():
                continue
            raw = pd.read_csv(path, usecols=v3_cols, low_memory=False)
            for gid, grp in raw.groupby("gameId"):
                q4 = q4_total_from_raw(grp)
                if q4 is not None:
                    rows.append(
                        {"game_id": str(gid).zfill(10), "q4_total": q4, "q4_pace48": q4 * 4.0}
                    )

    if not rows:
        return pd.DataFrame(columns=["game_id", "q4_total", "q4_pace48"])
    out = pd.DataFrame(rows).drop_duplicates("game_id")
    return out


def load_or_build_q4_pace(
    cache_path: Path,
    raw_dir: Path,
    *,
    seasons: Iterable[int],
    seasontype: str = "both",
    v3_archive_seasons: Iterable[int] | None = None,
    refresh: bool = False,
) -> pd.DataFrame:
    cache_path = Path(cache_path)
    if cache_path.exists() and not refresh:
        return pd.read_parquet(cache_path)
    df = build_q4_pace_table(
        raw_dir,
        seasons=seasons,
        seasontype=seasontype,
        v3_archive_seasons=v3_archive_seasons,
    )
    if not df.empty:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache_path, index=False)
    return df
