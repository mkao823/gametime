from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from gametime.config import resolve_path
from gametime.sports import get_sport

MLB_REFRESH_MODES = {"daily", "manual", "backfill"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as tmp:
        json.dump(payload, tmp, indent=2, default=str)
        tmp.flush()
        temp_path = Path(tmp.name)
    temp_path.replace(path)


def _mlb_ops_marker_dir(cfg: dict, root: Path) -> Path:
    ops_cfg = cfg.get("ops", {})
    return resolve_path(root, ops_cfg.get("marker_dir", "reports/mlb/ops"))


def _compute_games_max_date(games_path: Path) -> str | None:
    if not games_path.exists():
        return None
    games = pd.read_parquet(games_path)
    if games.empty or "game_date" not in games.columns:
        return None
    game_dates = pd.to_datetime(games["game_date"], errors="coerce").dropna()
    if game_dates.empty:
        return None
    return str(game_dates.max().date())


def _write_mlb_refresh_markers(cfg: dict, root: Path, payload: dict) -> dict[str, str]:
    marker_dir = _mlb_ops_marker_dir(cfg, root)
    last_path = marker_dir / "refresh_last.json"
    success_path = marker_dir / "refresh_success.json"
    failed_path = marker_dir / "refresh_failed.json"
    _write_json_atomic(last_path, payload)
    if payload.get("status") == "success":
        _write_json_atomic(success_path, payload)
    else:
        _write_json_atomic(failed_path, payload)
    return {
        "last": str(last_path),
        "success": str(success_path),
        "failed": str(failed_path),
    }


def _mlb_refresh_should_rebuild_sidecar(
    mode: str,
    *,
    force_refresh_flag: bool,
    sidecar_exists: bool,
    needs_train_backfill: bool,
) -> bool:
    if mode == "backfill":
        return True
    if force_refresh_flag or not sidecar_exists:
        return True
    if mode == "manual":
        return needs_train_backfill
    return False


def check_mlb_refresh_freshness(
    cfg: dict, root: Path, *, max_lag_days: int | None = None
) -> dict:
    data_cfg = cfg.get("data", {})
    games_path = resolve_path(
        root, data_cfg.get("games_path", "data/mlb/processed/games.parquet")
    )
    threshold = int(
        max_lag_days
        if max_lag_days is not None
        else data_cfg.get("games_freshness_max_lag_days", 1)
    )
    if not games_path.exists():
        return {
            "status": "failed",
            "message": f"missing games parquet: {games_path}",
            "games_path": str(games_path),
            "max_lag_days": threshold,
            "games_max_date": None,
            "lag_days": None,
        }
    games = pd.read_parquet(games_path)
    if games.empty or "game_date" not in games.columns:
        return {
            "status": "failed",
            "message": "games parquet is empty or missing game_date",
            "games_path": str(games_path),
            "max_lag_days": threshold,
            "games_max_date": None,
            "lag_days": None,
        }
    max_ts = pd.to_datetime(games["game_date"], errors="coerce").dropna()
    if max_ts.empty:
        return {
            "status": "failed",
            "message": "games parquet has no parseable game_date rows",
            "games_path": str(games_path),
            "max_lag_days": threshold,
            "games_max_date": None,
            "lag_days": None,
        }
    max_date = max_ts.max().date()
    lag_days = (datetime.now(timezone.utc).date() - max_date).days
    ok = lag_days <= threshold
    return {
        "status": "success" if ok else "failed",
        "message": (
            f"freshness ok: lag_days={lag_days} <= max_lag_days={threshold}"
            if ok
            else f"stale data: lag_days={lag_days} > max_lag_days={threshold}"
        ),
        "games_path": str(games_path),
        "max_lag_days": threshold,
        "games_max_date": str(max_date),
        "lag_days": lag_days,
    }


def run_mlb_refresh(cfg: dict, root: Path, *, mode: str = "daily") -> dict:
    normalized_mode = str(mode or "daily").strip().lower()
    if normalized_mode not in MLB_REFRESH_MODES:
        raise ValueError(
            f"invalid MLB refresh mode '{mode}' (expected one of {sorted(MLB_REFRESH_MODES)})"
        )

    data_cfg = cfg["data"]
    out = resolve_path(
        root, data_cfg.get("games_path", "data/mlb/processed/games.parquet")
    )
    pitcher_out = resolve_path(
        root,
        data_cfg.get("pitcher_games_path", "data/mlb/processed/pitcher_games.parquet"),
    )
    park_out = resolve_path(
        root,
        data_cfg.get("park_factors_path", "data/mlb/processed/park_factors.parquet"),
    )
    weather_out = resolve_path(
        root,
        data_cfg.get("weather_games_path", "data/mlb/processed/weather_games.parquet"),
    )
    lineup_out = resolve_path(
        root,
        data_cfg.get("lineup_games_path", "data/mlb/processed/lineup_games.parquet"),
    )
    statcast_out = resolve_path(
        root,
        data_cfg.get(
            "statcast_offense_games_path",
            "data/mlb/processed/statcast_offense_games.parquet",
        ),
    )
    managed_outputs = [out, pitcher_out, park_out, weather_out, lineup_out, statcast_out]
    for path in managed_outputs:
        path.parent.mkdir(parents=True, exist_ok=True)

    train_seasons = [int(s) for s in cfg.get("train", {}).get("train_seasons", [])]
    sidecar_min_frac = float(data_cfg.get("sidecar_train_min_frac", 0.85))
    pitcher_max_dates = data_cfg.get("pitcher_max_dates")
    lineup_max_dates = data_cfg.get("lineup_max_dates")
    statcast_max_dates = data_cfg.get("statcast_offense_max_dates")

    started_at = _utc_now_iso()
    started_ts = datetime.now(timezone.utc)
    stage = "init"
    backups: dict[Path, Path] = {}
    created: set[Path] = set()

    with tempfile.TemporaryDirectory(prefix="mlb-refresh-backup-") as backup_dir:
        backup_root = Path(backup_dir)
        for path in managed_outputs:
            if path.exists():
                backup_path = backup_root / path.name
                shutil.copy2(path, backup_path)
                backups[path] = backup_path

        try:
            from gametime.ingest.mlb import download_mlb_games
            from gametime.ingest.mlb_lineup import download_lineup_games
            from gametime.ingest.mlb_park import download_park_factors
            from gametime.ingest.mlb_pitchers import download_pitcher_games
            from gametime.ingest.mlb_statcast_offense import download_statcast_offense_games
            from gametime.ingest.mlb_weather import download_weather_games

            sport = get_sport(cfg)

            stage = "games"
            before = out.exists()
            download_mlb_games(
                out,
                seasons=[int(s) for s in data_cfg["seasons"]],
                teams=list(sport.mlb_teams) if sport.mlb_teams else None,
                statsapi_backfill_days=int(data_cfg.get("games_statsapi_backfill_days", 14)),
                statsapi_game_types=list(data_cfg.get("games_statsapi_game_types", ["R"])),
                statsapi_postseason_enabled=bool(
                    data_cfg.get("games_statsapi_postseason_enabled", False)
                ),
                statsapi_postseason_types=list(
                    data_cfg.get("games_statsapi_postseason_types", ["P", "F", "W", "D", "L"])
                ),
            )
            if not before and out.exists():
                created.add(out)

            needs_pitcher_backfill = (
                train_seasons
                and _sidecar_needs_train_backfill(
                    out,
                    pitcher_out,
                    train_seasons,
                    "has_starting_pitcher",
                    min_frac=sidecar_min_frac,
                )
            )
            if _mlb_refresh_should_rebuild_sidecar(
                normalized_mode,
                force_refresh_flag=bool(data_cfg.get("refresh_pitcher_games", False)),
                sidecar_exists=pitcher_out.exists(),
                needs_train_backfill=bool(needs_pitcher_backfill),
            ):
                stage = "pitcher_sidecar"
                before = pitcher_out.exists()
                cache_dir = resolve_path(
                    root, data_cfg.get("pitcher_cache_dir", "data/mlb/raw/pitcher_boxscores")
                )
                download_pitcher_games(
                    out,
                    pitcher_out,
                    min_season=int(data_cfg.get("pitcher_min_season", 2024)),
                    cache_dir=cache_dir,
                    max_dates=int(pitcher_max_dates) if pitcher_max_dates is not None else None,
                )
                if not before and pitcher_out.exists():
                    created.add(pitcher_out)

            if (
                normalized_mode == "backfill"
                or data_cfg.get("refresh_park_factors", False)
                or not park_out.exists()
            ):
                stage = "park_factors"
                before = park_out.exists()
                download_park_factors(
                    out,
                    park_out,
                    min_home_games=int(data_cfg.get("park_min_home_games", 30)),
                )
                if not before and park_out.exists():
                    created.add(park_out)

            if (
                normalized_mode == "backfill"
                or data_cfg.get("refresh_weather_games", False)
                or not weather_out.exists()
            ):
                stage = "weather"
                before = weather_out.exists()
                weather_cache_dir = resolve_path(
                    root, data_cfg.get("weather_cache_dir", "data/mlb/raw/weather_open_meteo")
                )
                download_weather_games(
                    out,
                    weather_out,
                    cache_dir=weather_cache_dir,
                )
                if not before and weather_out.exists():
                    created.add(weather_out)

            needs_lineup_backfill = (
                train_seasons
                and _sidecar_needs_train_backfill(
                    out,
                    lineup_out,
                    train_seasons,
                    "has_lineup",
                    min_frac=sidecar_min_frac,
                )
            )
            if _mlb_refresh_should_rebuild_sidecar(
                normalized_mode,
                force_refresh_flag=bool(data_cfg.get("refresh_lineup_games", False)),
                sidecar_exists=lineup_out.exists(),
                needs_train_backfill=bool(needs_lineup_backfill),
            ):
                stage = "lineup_sidecar"
                before = lineup_out.exists()
                lineup_cache = resolve_path(
                    root, data_cfg.get("lineup_cache_dir", "data/mlb/raw/lineup_woba")
                )
                box_cache = resolve_path(
                    root,
                    data_cfg.get("pitcher_cache_dir", "data/mlb/raw/pitcher_boxscores"),
                )
                download_lineup_games(
                    out,
                    lineup_out,
                    min_season=int(data_cfg.get("lineup_min_season", 2024)),
                    cache_dir=lineup_cache,
                    boxscore_cache_dir=box_cache,
                    max_dates=int(lineup_max_dates) if lineup_max_dates is not None else None,
                )
                if not before and lineup_out.exists():
                    created.add(lineup_out)

            needs_statcast_backfill = (
                train_seasons
                and _sidecar_needs_train_backfill(
                    out,
                    statcast_out,
                    train_seasons,
                    "has_statcast_offense",
                    min_frac=sidecar_min_frac,
                )
            )
            if _mlb_refresh_should_rebuild_sidecar(
                normalized_mode,
                force_refresh_flag=bool(data_cfg.get("refresh_statcast_offense_games", False)),
                sidecar_exists=statcast_out.exists(),
                needs_train_backfill=bool(needs_statcast_backfill),
            ):
                stage = "statcast_offense_sidecar"
                before = statcast_out.exists()
                statcast_cache = resolve_path(
                    root,
                    data_cfg.get("statcast_offense_cache_dir", "data/mlb/raw/statcast_offense"),
                )
                download_statcast_offense_games(
                    out,
                    statcast_out,
                    min_season=int(data_cfg.get("statcast_offense_min_season", 2021)),
                    cache_dir=statcast_cache,
                    max_dates=int(statcast_max_dates)
                    if statcast_max_dates is not None
                    else None,
                )
                if not before and statcast_out.exists():
                    created.add(statcast_out)

            finished_ts = datetime.now(timezone.utc)
            payload = {
                "status": "success",
                "mode": normalized_mode,
                "started_at": started_at,
                "finished_at": _utc_now_iso(),
                "elapsed_seconds": round((finished_ts - started_ts).total_seconds(), 3),
                "games_max_date": _compute_games_max_date(out),
                "output_path": str(out),
            }
            payload["marker_paths"] = _write_mlb_refresh_markers(cfg, root, payload)
            return payload
        except Exception as exc:
            for target, backup in backups.items():
                shutil.copy2(backup, target)
            for target in created:
                if target.exists() and target not in backups:
                    target.unlink()
            finished_ts = datetime.now(timezone.utc)
            payload = {
                "status": "failed",
                "mode": normalized_mode,
                "started_at": started_at,
                "finished_at": _utc_now_iso(),
                "elapsed_seconds": round((finished_ts - started_ts).total_seconds(), 3),
                "games_max_date": _compute_games_max_date(out),
                "failed_stage": stage,
                "error": str(exc),
            }
            payload["marker_paths"] = _write_mlb_refresh_markers(cfg, root, payload)
            raise RuntimeError(json.dumps(payload, default=str)) from exc


def v3_archive_seasons(data_cfg: dict) -> list[int]:
    seasons: list[int] = []
    for sup in data_cfg.get("supplemental_pbp", []):
        if sup.get("source") == "nbastatsv3":
            seasons.extend(int(s) for s in sup.get("seasons", []))
    return seasons


def _sidecar_train_coverage_frac(
    games_path: Path,
    sidecar_path: Path,
    train_seasons: list[int],
    flag_col: str,
    *,
    seasontype: str = "rg",
) -> float:
    """Fraction of train-season RS games with ``flag_col == 1`` in the sidecar."""
    if not sidecar_path.exists():
        return 0.0
    games = pd.read_parquet(games_path)
    sidecar = pd.read_parquet(sidecar_path)
    if sidecar.empty or flag_col not in sidecar.columns:
        return 0.0
    train = games[
        games["season_start_year"].isin(train_seasons)
        & (games.get("seasontype", seasontype) == seasontype)
    ]
    if train.empty:
        return 1.0
    merged = train[["game_id"]].merge(
        sidecar[["game_id", flag_col]].drop_duplicates("game_id"),
        on="game_id",
        how="left",
    )
    return float((merged[flag_col].fillna(0).astype(int) == 1).mean())


def _sidecar_needs_train_backfill(
    games_path: Path,
    sidecar_path: Path,
    train_seasons: list[int],
    flag_col: str,
    *,
    min_frac: float = 0.85,
    seasontype: str = "rg",
) -> bool:
    return _sidecar_train_coverage_frac(
        games_path,
        sidecar_path,
        train_seasons,
        flag_col,
        seasontype=seasontype,
    ) < min_frac


def run_download(cfg: dict, root: Path) -> Path:
    sport = get_sport(cfg)
    if sport.family == "baseball":
        result = run_mlb_refresh(cfg, root, mode="manual")
        return Path(result["output_path"])

    from gametime.data.download import load_nba_data

    data_cfg = cfg["data"]
    raw_dir = resolve_path(root, data_cfg["raw_dir"])
    raw_dir.mkdir(parents=True, exist_ok=True)
    st = data_cfg.get("seasontype", "rg")
    if st == "both":
        for seasontype in ("rg", "po"):
            for season in data_cfg["seasons"]:
                load_nba_data(
                    path=raw_dir,
                    seasons=season,
                    data=(data_cfg["source"],),
                    seasontype=seasontype,
                    untar=True,
                    in_memory=False,
                )
    else:
        for season in data_cfg["seasons"]:
            load_nba_data(
                path=raw_dir,
                seasons=season,
                data=(data_cfg["source"],),
                seasontype=st,
                untar=True,
                in_memory=False,
            )
    for sup in data_cfg.get("supplemental_pbp", []):
        src = sup["source"]
        for season in sup.get("seasons", []):
            st_sup = sup.get("seasontype", "rg")
            load_nba_data(
                path=raw_dir,
                seasons=season,
                data=(src,),
                seasontype=st_sup,
                untar=True,
                in_memory=False,
            )
    return raw_dir


def run_download_basketball(cfg: dict, root: Path) -> Path:
    """Backward-compatible alias; prefer run_download."""
    return run_download(cfg, root)


def load_raw_pbp(raw_dir: Path, source: str, seasons: list, seasontype: str = "both") -> pd.DataFrame:
    frames = []
    types = ("rg", "po") if seasontype == "both" else (seasontype,)
    for st in types:
        for season in seasons:
            suffix = f"_{season}" if st == "rg" else f"_po_{season}"
            path = raw_dir / f"{source}{suffix}.csv"
            if path.exists():
                frames.append(pd.read_csv(path, low_memory=False))
    if not frames:
        raise FileNotFoundError(f"No CSVs in {raw_dir} for {source} seasons={seasons} type={seasontype}")
    return pd.concat(frames, ignore_index=True)


def run_build(cfg: dict, root: Path) -> Path:
    from gametime.data.game_meta import annotate_games
    from gametime.data.pbp import normalize_nbastats_pbp
    from gametime.features.engineering import add_model_features
    from gametime.features.pregame_join import (
        add_pregame_feature_defaults,
        add_pregame_features,
        build_pregame_lookup,
    )
    from gametime.features.snapshots import build_snapshots
    from gametime.pregame.elo import EloParams

    sport = get_sport(cfg)
    if not sport.has("ingame"):
        raise ValueError(
            f"{sport.name} has no in-game model (capabilities={sorted(sport.capabilities)}). "
            "Use gametime-pregame-train for pregame-only sports."
        )
    data_cfg = cfg["data"]
    snap_cfg = cfg["snapshots"]
    feat_cfg = cfg["features"]
    league = sport
    raw_dir = resolve_path(root, data_cfg["raw_dir"])
    out_dir = resolve_path(root, data_cfg["processed_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = load_raw_pbp(raw_dir, data_cfg["source"], data_cfg["seasons"], data_cfg.get("seasontype", "both"))
    events = normalize_nbastats_pbp(
        raw,
        period_length_sec=league.period_length_sec,
        regulation_periods=league.regulation_periods,
    )
    regulation_seconds = int(
        snap_cfg.get("regulation_seconds", league.regulation_seconds)
    )
    snapshots = build_snapshots(
        events,
        interval_seconds=snap_cfg["interval_seconds"],
        regulation_seconds=regulation_seconds,
    )
    base_snap_path = out_dir / "_snapshots_base.parquet"
    snapshots.to_parquet(base_snap_path, index=False)
    featured = add_model_features(
        snapshots,
        interval_seconds=snap_cfg["interval_seconds"],
        rolling_window_seconds=feat_cfg["rolling_window_seconds"],
        long_window_seconds=feat_cfg.get("long_window_seconds", 600),
        regulation_minutes=league.regulation_minutes,
        period_length_sec=league.period_length_sec,
    )
    featured = annotate_games(featured, league=league)
    pg_cfg = cfg.get("pregame", {})
    if pg_cfg.get("join_in_game", True):
        try:
            lookup = build_pregame_lookup(
                root,
                raw_dir=raw_dir,
                snapshots_path=base_snap_path,
                team_games_path=resolve_path(root, pg_cfg.get("team_games_path", "data/processed/team_games.parquet")),
                pregame_model_dir=resolve_path(root, pg_cfg.get("model_dir", "models/pregame")),
                seasons=data_cfg["seasons"],
                form_window=int(pg_cfg.get("form_window", 10)),
                elo_params=EloParams(**pg_cfg.get("elo", {})) if pg_cfg.get("elo") else None,
                v3_archive_seasons=v3_archive_seasons(data_cfg),
                pbp_source=data_cfg.get("source", "nbastats"),
                league=league,
            )
            featured = add_pregame_features(
                featured,
                lookup,
                league_total_fallback=float(
                    pg_cfg.get("league_total_fallback", 225.8)
                ),
            )
            lookup.to_parquet(out_dir / "pregame_lookup.parquet", index=False)
        except FileNotFoundError as exc:
            print(f"Warning: skipping pregame join — {exc}")
    elif sport.has("pregame"):
        featured = add_pregame_feature_defaults(
            featured,
            league_total_fallback=float(
                pg_cfg.get("league_total_fallback", league.league_total_fallback)
            ),
        )
    out_path = out_dir / "snapshots.parquet"
    featured.to_parquet(out_path, index=False)
    return out_path


def run_train(cfg: dict, root: Path) -> Path:
    from gametime.models.train import train_models

    data_cfg = cfg["data"]
    train_cfg = cfg["train"]
    processed = resolve_path(root, data_cfg["processed_dir"]) / "snapshots.parquet"
    df = pd.read_parquet(processed)
    model_dir = resolve_path(root, train_cfg["model_dir"])
    train_models(df, model_dir=model_dir, cfg=cfg)
    return model_dir


def run_eval(cfg: dict, root: Path) -> dict:
    from gametime.evaluate.holdout import run_holdout_eval

    data_cfg = cfg["data"]
    train_cfg = cfg["train"]
    eval_cfg = cfg["evaluate"]
    processed = resolve_path(root, data_cfg["processed_dir"]) / "snapshots.parquet"
    model_dir = resolve_path(root, train_cfg["model_dir"])
    report_dir = resolve_path(root, eval_cfg["report_dir"])
    return run_holdout_eval(pd.read_parquet(processed), model_dir, cfg, report_dir)


def run_signals(cfg: dict, root: Path) -> dict:
    from gametime.evaluate.signals import run_signal_backtest

    data_cfg = cfg["data"]
    train_cfg = cfg["train"]
    sig_cfg = cfg["signals"]
    processed = resolve_path(root, data_cfg["processed_dir"]) / "snapshots.parquet"
    model_dir = resolve_path(root, train_cfg["model_dir"])
    report_dir = resolve_path(root, sig_cfg["report_dir"])
    return run_signal_backtest(pd.read_parquet(processed), model_dir, cfg, report_dir)
