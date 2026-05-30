"""Slate CLI numeric formatting (W6-slate-precision)."""
from __future__ import annotations

import io
import sys
from unittest.mock import MagicMock, patch

from gametime.cli import pregame_slate


@patch("gametime.pregame.log.log_pregame_prediction")
@patch("gametime.pregame.baseball.predict.BaseballPregamePredictor")
@patch("gametime.ingest.mlb.slate_matchups_for_date")
@patch("gametime.cli.load_config")
@patch("gametime.cli.project_root")
def test_pregame_slate_decimals_default_two(
    mock_root, mock_load, mock_matchups, mock_predictor_cls, _mock_log
):
    mock_root.return_value = MagicMock()
    mock_load.return_value = {
        "data": {"games_path": "data/mlb/processed/games.parquet"},
        "pregame": {"model_dir": "models/mlb/pregame", "form_window": 10, "ensemble": {}},
        "train": {"model_dir": "models/mlb/pregame", "train_seasons": [2024]},
        "live": {"log_dir": "data/live_predictions"},
    }
    mock_matchups.return_value = [{"away": "CHC", "home": "STL"}]

    pred = MagicMock()
    pred.pred_total = 8.456
    pred.pred_margin = 0.123
    pred.winner_tricode = "STL"
    mock_predictor_cls.return_value.predict.return_value = pred

    with patch("gametime.sports.get_sport") as mock_sport:
        sport = MagicMock()
        sport.family = "baseball"
        sport.mlb_teams = None
        mock_sport.return_value = sport

        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            pregame_slate(
                [
                    "--config",
                    "configs/mlb.yaml",
                    "--date",
                    "2026-05-29",
                    "--regular-season",
                    "--no-log",
                ]
            )
        finally:
            sys.stdout = old_stdout

    out = buf.getvalue()
    assert "8.46" in out
    assert " +0.12" in out or "+0.12" in out


@patch("gametime.pregame.log.log_pregame_prediction")
@patch("gametime.pregame.baseball.predict.BaseballPregamePredictor")
@patch("gametime.ingest.mlb.slate_matchups_for_date")
@patch("gametime.cli.load_config")
@patch("gametime.cli.project_root")
def test_pregame_slate_decimals_one(
    mock_root, mock_load, mock_matchups, mock_predictor_cls, _mock_log
):
    mock_root.return_value = MagicMock()
    mock_load.return_value = {
        "data": {"games_path": "data/mlb/processed/games.parquet"},
        "pregame": {"model_dir": "models/mlb/pregame", "form_window": 10, "ensemble": {}},
        "train": {"model_dir": "models/mlb/pregame", "train_seasons": [2024]},
        "live": {"log_dir": "data/live_predictions"},
    }
    mock_matchups.return_value = [{"away": "CHC", "home": "STL"}]

    pred = MagicMock()
    pred.pred_total = 8.456
    pred.pred_margin = 0.123
    pred.winner_tricode = "STL"
    mock_predictor_cls.return_value.predict.return_value = pred

    with patch("gametime.sports.get_sport") as mock_sport:
        sport = MagicMock()
        sport.family = "baseball"
        sport.mlb_teams = None
        mock_sport.return_value = sport

        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            pregame_slate(
                [
                    "--config",
                    "configs/mlb.yaml",
                    "--date",
                    "2026-05-29",
                    "--regular-season",
                    "--no-log",
                    "--decimals",
                    "1",
                ]
            )
        finally:
            sys.stdout = old_stdout

    out = buf.getvalue()
    assert "8.5" in out
    assert " +0.1" in out or "+0.1" in out
