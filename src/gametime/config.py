from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from gametime.sports import NBA, get_sport


def _deep_merge_missing(dst: dict[str, Any], src: dict[str, Any]) -> None:
    """Fill *dst* with keys from *src* only where *dst* has no value."""
    for key, value in src.items():
        if key not in dst:
            dst[key] = deepcopy(value)
        elif isinstance(value, dict) and isinstance(dst.get(key), dict):
            _deep_merge_missing(dst[key], value)


def sport_output_defaults(sport_id: str) -> dict[str, Any]:
    """Per-sport output directories (relative to project root).

    NBA keeps legacy paths (``data/raw``, ``reports/eval``, …).
    Other sports nest under ``data/<sport>/``, ``models/<sport>/``, ``reports/<sport>/``.
    """
    if sport_id == "nba":
        return {
            "data": {
                "raw_dir": "data/raw",
                "processed_dir": "data/processed",
            },
            "train": {"model_dir": "models"},
            "evaluate": {"report_dir": "reports/eval"},
            "signals": {"report_dir": "reports/signals"},
            "live": {
                "log_dir": "data/live_predictions",
                "analysis_dir": "reports/live_analysis",
                "json_report_dir": "reports/live",
            },
            "pregame": {
                "model_dir": "models/pregame",
                "team_games_path": "data/processed/team_games.parquet",
                "report_path": "reports/eval/pregame_summary.json",
            },
        }
    if sport_id == "wnba":
        return {
            "data": {
                "raw_dir": "data/wnba/raw",
                "processed_dir": "data/wnba/processed",
            },
            "train": {"model_dir": "models/wnba"},
            "evaluate": {"report_dir": "reports/wnba/eval"},
            "signals": {"report_dir": "reports/wnba/signals"},
            "live": {
                "log_dir": "data/wnba/live_predictions",
                "analysis_dir": "reports/wnba/live_analysis",
                "json_report_dir": "reports/wnba/live",
            },
            "pregame": {
                "model_dir": "models/wnba/pregame",
                "team_games_path": "data/wnba/processed/team_games.parquet",
                "report_path": "reports/wnba/eval/pregame_summary.json",
            },
        }
    if sport_id == "mlb":
        return {
            "data": {
                "processed_dir": "data/mlb/processed",
                "games_path": "data/mlb/processed/games.parquet",
            },
            "train": {"model_dir": "models/mlb/pregame"},
            "pregame": {
                "model_dir": "models/mlb/pregame",
                "games_path": "data/mlb/processed/games.parquet",
                "report_path": "reports/mlb/eval/pregame_summary.json",
            },
        }
    return {}


def apply_sport_defaults(cfg: dict[str, Any]) -> dict[str, Any]:
    sport_id = get_sport(cfg).id
    out = deepcopy(cfg)
    _deep_merge_missing(out, sport_output_defaults(sport_id))
    return out


def load_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open() as f:
        cfg = yaml.safe_load(f) or {}
    return apply_sport_defaults(cfg)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_path(base: Path, p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else base / path
