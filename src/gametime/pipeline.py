from __future__ import annotations

from pathlib import Path

import pandas as pd

from gametime.config import load_config, project_root, resolve_path
from gametime.data.download import load_nba_data
from gametime.data.game_meta import annotate_games
from gametime.data.pbp import normalize_nbastats_pbp
from gametime.evaluate.holdout import run_holdout_eval
from gametime.evaluate.signals import run_signal_backtest
from gametime.features.engineering import add_model_features
from gametime.features.pregame_join import (
    add_pregame_feature_defaults,
    add_pregame_features,
    build_pregame_lookup,
)
from gametime.features.snapshots import build_snapshots
from gametime.sports import get_sport
from gametime.pregame.elo import EloParams
from gametime.models.train import train_models


def v3_archive_seasons(data_cfg: dict) -> list[int]:
    seasons: list[int] = []
    for sup in data_cfg.get("supplemental_pbp", []):
        if sup.get("source") == "nbastatsv3":
            seasons.extend(int(s) for s in sup.get("seasons", []))
    return seasons


def run_download(cfg: dict, root: Path) -> Path:
    sport = get_sport(cfg)
    if sport.family == "baseball":
        from gametime.ingest.mlb import download_mlb_games

        data_cfg = cfg["data"]
        out = resolve_path(root, data_cfg.get("games_path", "data/mlb/processed/games.parquet"))
        download_mlb_games(
            out,
            seasons=[int(s) for s in data_cfg["seasons"]],
            teams=list(sport.mlb_teams) if sport.mlb_teams else None,
        )
        pitcher_out = resolve_path(
            root,
            data_cfg.get(
                "pitcher_games_path", "data/mlb/processed/pitcher_games.parquet"
            ),
        )
        if data_cfg.get("refresh_pitcher_games", False) or not pitcher_out.exists():
            from gametime.ingest.mlb_pitchers import download_pitcher_games

            cache_dir = resolve_path(
                root, data_cfg.get("pitcher_cache_dir", "data/mlb/raw/pitcher_boxscores")
            )
            download_pitcher_games(
                out,
                pitcher_out,
                min_season=int(data_cfg.get("pitcher_min_season", 2024)),
                cache_dir=cache_dir,
            )
        park_out = resolve_path(
            root,
            data_cfg.get(
                "park_factors_path", "data/mlb/processed/park_factors.parquet"
            ),
        )
        if data_cfg.get("refresh_park_factors", False) or not park_out.exists():
            from gametime.ingest.mlb_park import download_park_factors

            download_park_factors(
                out,
                park_out,
                min_home_games=int(data_cfg.get("park_min_home_games", 30)),
            )
        return out

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
    data_cfg = cfg["data"]
    train_cfg = cfg["train"]
    processed = resolve_path(root, data_cfg["processed_dir"]) / "snapshots.parquet"
    df = pd.read_parquet(processed)
    model_dir = resolve_path(root, train_cfg["model_dir"])
    train_models(df, model_dir=model_dir, cfg=cfg)
    return model_dir


def run_eval(cfg: dict, root: Path) -> dict:
    data_cfg = cfg["data"]
    train_cfg = cfg["train"]
    eval_cfg = cfg["evaluate"]
    processed = resolve_path(root, data_cfg["processed_dir"]) / "snapshots.parquet"
    model_dir = resolve_path(root, train_cfg["model_dir"])
    report_dir = resolve_path(root, eval_cfg["report_dir"])
    return run_holdout_eval(pd.read_parquet(processed), model_dir, cfg, report_dir)


def run_signals(cfg: dict, root: Path) -> dict:
    data_cfg = cfg["data"]
    train_cfg = cfg["train"]
    sig_cfg = cfg["signals"]
    processed = resolve_path(root, data_cfg["processed_dir"]) / "snapshots.parquet"
    model_dir = resolve_path(root, train_cfg["model_dir"])
    report_dir = resolve_path(root, sig_cfg["report_dir"])
    return run_signal_backtest(pd.read_parquet(processed), model_dir, cfg, report_dir)
