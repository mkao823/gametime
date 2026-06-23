from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from gametime.pipeline import check_mlb_refresh_freshness, run_mlb_refresh


def _write_games(path: Path, game_date: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "game_id": "g1",
                "game_date": pd.Timestamp(game_date),
                "home_team": "NYY",
                "away_team": "BOS",
                "season_start_year": 2026,
                "seasontype": "rg",
            }
        ]
    ).to_parquet(path, index=False)


def _base_cfg(tmp_path: Path) -> dict:
    return {
        "sport": "mlb",
        "data": {
            "seasons": [2026],
            "games_path": "data/mlb/processed/games.parquet",
            "pitcher_games_path": "data/mlb/processed/pitcher_games.parquet",
            "park_factors_path": "data/mlb/processed/park_factors.parquet",
            "weather_games_path": "data/mlb/processed/weather_games.parquet",
            "lineup_games_path": "data/mlb/processed/lineup_games.parquet",
            "statcast_offense_games_path": "data/mlb/processed/statcast_offense_games.parquet",
            "games_freshness_max_lag_days": 1,
            "refresh_pitcher_games": False,
            "refresh_park_factors": False,
            "refresh_weather_games": False,
            "refresh_lineup_games": False,
            "refresh_statcast_offense_games": False,
        },
        "train": {"train_seasons": [2026]},
        "ops": {"marker_dir": str(tmp_path / "reports/mlb/ops")},
    }


@patch("gametime.pipeline._sidecar_needs_train_backfill", return_value=True)
@patch("gametime.ingest.mlb_statcast_offense.download_statcast_offense_games")
@patch("gametime.ingest.mlb_lineup.download_lineup_games")
@patch("gametime.ingest.mlb_weather.download_weather_games")
@patch("gametime.ingest.mlb_park.download_park_factors")
@patch("gametime.ingest.mlb_pitchers.download_pitcher_games")
@patch("gametime.ingest.mlb.download_mlb_games")
def test_run_mlb_refresh_daily_skips_train_backfill_sidecars(
    mock_download_games,
    mock_pitchers,
    _mock_park,
    _mock_weather,
    mock_lineup,
    mock_statcast,
    _mock_backfill_gate,
    tmp_path: Path,
):
    cfg = _base_cfg(tmp_path)
    games_path = tmp_path / cfg["data"]["games_path"]
    for sidecar_rel in (
        cfg["data"]["pitcher_games_path"],
        cfg["data"]["lineup_games_path"],
        cfg["data"]["statcast_offense_games_path"],
    ):
        sidecar_path = tmp_path / sidecar_rel
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([{"game_id": "seed"}]).to_parquet(sidecar_path, index=False)

    def fake_games(*args, **kwargs):
        _write_games(games_path, "2026-06-20")

    mock_download_games.side_effect = fake_games
    summary = run_mlb_refresh(cfg, tmp_path, mode="daily")
    assert summary["status"] == "success"
    assert summary["mode"] == "daily"
    assert summary["games_max_date"] == "2026-06-20"
    assert mock_pitchers.call_count == 0
    assert mock_lineup.call_count == 0
    assert mock_statcast.call_count == 0
    marker_path = Path(summary["marker_paths"]["last"])
    payload = json.loads(marker_path.read_text(encoding="utf-8"))
    assert payload["status"] == "success"


@patch("gametime.pipeline._sidecar_needs_train_backfill", return_value=False)
@patch("gametime.ingest.mlb_statcast_offense.download_statcast_offense_games")
@patch("gametime.ingest.mlb_lineup.download_lineup_games")
@patch("gametime.ingest.mlb_weather.download_weather_games")
@patch("gametime.ingest.mlb_park.download_park_factors")
@patch("gametime.ingest.mlb_pitchers.download_pitcher_games")
@patch("gametime.ingest.mlb.download_mlb_games")
def test_run_mlb_refresh_backfill_routes_to_sidecar_rebuilds(
    mock_download_games,
    mock_pitchers,
    mock_park,
    mock_weather,
    mock_lineup,
    mock_statcast,
    _mock_backfill_gate,
    tmp_path: Path,
):
    cfg = _base_cfg(tmp_path)
    games_path = tmp_path / cfg["data"]["games_path"]

    def fake_games(*args, **kwargs):
        _write_games(games_path, "2026-06-21")

    mock_download_games.side_effect = fake_games
    run_mlb_refresh(cfg, tmp_path, mode="backfill")
    assert mock_pitchers.call_count == 1
    assert mock_park.call_count == 1
    assert mock_weather.call_count == 1
    assert mock_lineup.call_count == 1
    assert mock_statcast.call_count == 1


@patch("gametime.ingest.mlb_statcast_offense.download_statcast_offense_games")
@patch("gametime.ingest.mlb_lineup.download_lineup_games")
@patch("gametime.ingest.mlb_weather.download_weather_games")
@patch("gametime.ingest.mlb_park.download_park_factors")
@patch("gametime.ingest.mlb_pitchers.download_pitcher_games")
@patch("gametime.ingest.mlb.download_mlb_games")
def test_run_mlb_refresh_failure_restores_prior_games_file(
    mock_download_games,
    mock_pitchers,
    _mock_park,
    _mock_weather,
    _mock_lineup,
    _mock_statcast,
    tmp_path: Path,
):
    cfg = _base_cfg(tmp_path)
    cfg["data"]["refresh_pitcher_games"] = True
    games_path = tmp_path / cfg["data"]["games_path"]
    _write_games(games_path, "2026-06-15")

    def fake_games(*args, **kwargs):
        _write_games(games_path, "2026-06-23")

    mock_download_games.side_effect = fake_games
    mock_pitchers.side_effect = RuntimeError("pitcher stage exploded")

    with pytest.raises(RuntimeError):
        run_mlb_refresh(cfg, tmp_path, mode="daily")

    restored = pd.read_parquet(games_path)
    assert str(pd.to_datetime(restored["game_date"]).max().date()) == "2026-06-15"
    failed_marker = Path(cfg["ops"]["marker_dir"]) / "refresh_failed.json"
    payload = json.loads(failed_marker.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["failed_stage"] == "pitcher_sidecar"


def test_check_mlb_refresh_freshness_pass_and_fail(tmp_path: Path):
    cfg = _base_cfg(tmp_path)
    games_path = tmp_path / cfg["data"]["games_path"]
    yesterday = (pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=1)).date()
    _write_games(games_path, str(yesterday))

    ok = check_mlb_refresh_freshness(cfg, tmp_path, max_lag_days=1)
    assert ok["status"] == "success"

    stale = check_mlb_refresh_freshness(cfg, tmp_path, max_lag_days=0)
    assert stale["status"] == "failed"
