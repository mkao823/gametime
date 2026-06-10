"""Config load, predictor factory, and shared API helpers."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from gametime.config import load_config, project_root, resolve_path
from gametime.ingest.mlb import infer_season_start_year, slate_matchups_for_date
from gametime.pregame.baseball.models.elo import BaseballEloParams
from gametime.pregame.baseball.predict import (
    BaseballPregamePrediction,
    BaseballPregamePredictor,
)
from gametime.sports import get_sport

_TRICODE_RE = re.compile(r"^[A-Z]{2,3}$")


@dataclass
class AppSettings:
    root: Path
    config_path: Path
    cfg: dict[str, Any]


@dataclass
class AppState:
    settings: AppSettings
    predictor: BaseballPregamePredictor
    model_dir: Path
    games_path: Path
    mlb_teams: frozenset[str]


def resolve_settings(
    *,
    root: Optional[Path] = None,
    config_path: Optional[Path] = None,
) -> AppSettings:
    """Load YAML config from env or explicit paths."""
    resolved_root = Path(root or os.environ.get("GAMETIME_ROOT", project_root()))
    cfg_rel = os.environ.get("GAMETIME_CONFIG", "configs/mlb.yaml")
    resolved_config = Path(config_path) if config_path else resolved_root / cfg_rel
    cfg = load_config(resolved_config)
    return AppSettings(root=resolved_root, config_path=resolved_config, cfg=cfg)


def build_predictor_from_config(
    root: Path,
    config_path: Path,
    cfg: Optional[dict[str, Any]] = None,
) -> tuple[BaseballPregamePredictor, Path, Path]:
    """Construct BaseballPregamePredictor with the same kwargs as CLI pregame_slate."""
    cfg = cfg or load_config(config_path)
    sport = get_sport(cfg)
    if sport.family != "baseball":
        raise ValueError("Predictions API v1 supports MLB (sport: mlb) only.")

    pg = cfg.get("pregame", {})
    data_cfg = cfg.get("data", {})
    train_cfg = cfg.get("train", {})
    ensemble_cfg = pg.get("ensemble", {})
    elo_cfg = pg.get("elo", {})
    h2h_cfg = pg.get("h2h", {})

    games_path = resolve_path(root, pg.get("games_path", data_cfg.get("games_path")))
    model_dir = resolve_path(root, pg.get("model_dir", train_cfg["model_dir"]))
    baseball_elo_params = BaseballEloParams(
        k=float(elo_cfg.get("k", 4.0)),
        home_adv_runs=float(elo_cfg.get("home_adv_runs", 0.15)),
        season_regression=float(elo_cfg.get("season_regression", 0.25)),
        margin_elo_scale=float(elo_cfg.get("margin_elo_scale", 50.0)),
    )
    pitcher_games_path = resolve_path(
        root, data_cfg.get("pitcher_games_path", "data/mlb/processed/pitcher_games.parquet")
    )
    park_factors_path = resolve_path(
        root, data_cfg.get("park_factors_path", "data/mlb/processed/park_factors.parquet")
    )
    weather_games_path = resolve_path(
        root, data_cfg.get("weather_games_path", "data/mlb/processed/weather_games.parquet")
    )
    lineup_games_path = resolve_path(
        root, data_cfg.get("lineup_games_path", "data/mlb/processed/lineup_games.parquet")
    )
    total_cal_enabled = bool(pg.get("calibration", {}).get("total_enabled", False))

    predictor = BaseballPregamePredictor(
        model_dir,
        games_path,
        form_window=int(pg.get("form_window", 10)),
        runs_strength_window=int(ensemble_cfg.get("runs_strength_window", 30)),
        train_seasons=train_cfg["train_seasons"],
        train_seasontypes=train_cfg.get("train_seasontypes", ["rg"]),
        use_stacking=bool(ensemble_cfg.get("use_stacking", False)),
        elo_params=baseball_elo_params,
        pitcher_games_path=pitcher_games_path,
        park_factors_path=park_factors_path,
        weather_games_path=weather_games_path,
        lineup_games_path=lineup_games_path,
        league_total_fallback=float(pg.get("league_total_fallback", 8.5)),
        h2h_window=int(h2h_cfg.get("meeting_window", 10)),
        h2h_shrink_k=float(h2h_cfg.get("shrink_k", 8.0)),
        total_calibration_enabled=total_cal_enabled,
    )
    return predictor, model_dir, games_path


def init_state(
    *,
    root: Optional[Path] = None,
    config_path: Optional[Path] = None,
    predictor: Optional[BaseballPregamePredictor] = None,
) -> AppState:
    settings = resolve_settings(root=root, config_path=config_path)
    sport = get_sport(settings.cfg)
    if predictor is None:
        predictor, model_dir, games_path = build_predictor_from_config(
            settings.root, settings.config_path, settings.cfg
        )
    else:
        pg = settings.cfg.get("pregame", {})
        data_cfg = settings.cfg.get("data", {})
        train_cfg = settings.cfg.get("train", {})
        games_path = resolve_path(
            settings.root, pg.get("games_path", data_cfg.get("games_path"))
        )
        model_dir = resolve_path(
            settings.root, pg.get("model_dir", train_cfg["model_dir"])
        )

    teams = frozenset(sport.mlb_teams) if sport.mlb_teams else frozenset()
    return AppState(
        settings=settings,
        predictor=predictor,
        model_dir=model_dir,
        games_path=games_path,
        mlb_teams=teams,
    )


def games_max_date(games: pd.DataFrame) -> Optional[str]:
    if games.empty or "game_date" not in games.columns:
        return None
    return pd.to_datetime(games["game_date"]).max().date().isoformat()


def relative_to_root(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def validate_tricode(value: str, *, allowed: frozenset[str]) -> str:
    code = value.strip().upper()
    if not _TRICODE_RE.match(code):
        raise ValueError(f"Invalid tricode '{value}': expected 2–3 uppercase letters.")
    if allowed and code not in allowed:
        raise ValueError(f"Unknown MLB tricode '{code}'.")
    return code


def slate_for_date(
    state: AppState,
    slate_date: date,
    *,
    regular_season: bool,
) -> list[dict[str, Any]]:
    sport = get_sport(state.settings.cfg)
    season = infer_season_start_year(slate_date)
    return slate_matchups_for_date(
        slate_date,
        season_start_year=season,
        games_path=state.games_path,
        teams=sport.mlb_teams or None,
        regular_season_only=regular_season,
    )


def matchup_on_slate(
    state: AppState,
    *,
    home: str,
    away: str,
    slate_date: date,
    regular_season: bool,
) -> bool:
    home_u, away_u = home.upper(), away.upper()
    for m in slate_for_date(state, slate_date, regular_season=regular_season):
        if m["home"].upper() == home_u and m["away"].upper() == away_u:
            return True
    return False


def to_game_prediction(
    pred: BaseballPregamePrediction,
    slate_date: date,
    *,
    include_members: bool = False,
    start_time: Optional[str] = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "home": pred.home_tricode,
        "away": pred.away_tricode,
        "date": slate_date.isoformat(),
        "pred_total": pred.pred_total,
        "pred_margin": pred.pred_margin,
        "pred_home_final": pred.pred_home_final,
        "pred_away_final": pred.pred_away_final,
        "winner": pred.winner_tricode,
        "win_prob_home": pred.win_prob_home,
        "is_playoff": pred.is_playoff,
        "home_form_n": pred.home_form_n,
        "away_form_n": pred.away_form_n,
    }
    if include_members:
        out["member_totals"] = pred.member_totals or {}
        out["member_margins"] = pred.member_margins or {}
    if start_time is not None:
        out["start_time"] = start_time
    return out
