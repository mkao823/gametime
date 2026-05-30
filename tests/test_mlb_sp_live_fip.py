"""Live slate starting-pitcher FIP lookup (W6-sp-live-fip)."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from gametime.ingest.mlb_pitchers import LEAGUE_FIP, fip_prior_for_pitcher_id
from gametime.pregame.baseball.models.pitcher import latest_pitcher_columns


def _games_and_sidecar() -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.to_datetime(["2024-04-01", "2024-04-05", "2024-04-08"])
    games = pd.DataFrame(
        {
            "game_id": ["g1", "g2", "g3"],
            "game_date": dates,
            "home_team": ["AAA", "BBB", "AAA"],
            "away_team": ["BBB", "AAA", "BBB"],
            "home_runs": [3, 4, 5],
            "away_runs": [2, 3, 4],
            "margin_final": [1, 1, 1],
            "season_start_year": [2024, 2024, 2024],
            "seasontype": ["rg", "rg", "rg"],
        }
    )
    pitcher_games = pd.DataFrame(
        {
            "game_id": ["g1", "g2", "g3"],
            "home_sp_id": [100, 300, 100],
            "away_sp_id": [200, 100, 200],
            "home_sp_fip": [3.20, 4.50, 3.10],
            "away_sp_fip": [5.10, 3.20, 5.00],
            "home_sp_rest_days": [5.0, 5.0, 4.0],
            "away_sp_rest_days": [5.0, 4.0, 5.0],
            "has_starting_pitcher": [1, 1, 1],
        }
    )
    return games, pitcher_games


@patch("gametime.pregame.baseball.models.pitcher.fetch_probable_pitchers")
def test_latest_pitcher_columns_distinct_fip_per_probable(mock_fetch):
    games, pitcher_games = _games_and_sidecar()
    mock_fetch.return_value = (100, 200)
    cols = latest_pitcher_columns(
        home="AAA",
        away="BBB",
        games=games,
        pitcher_games=pitcher_games,
        game_date=date(2024, 4, 10),
    )
    assert cols["has_starting_pitcher"] == 1
    assert cols["home_sp_fip"] == pytest.approx(3.10)
    assert cols["away_sp_fip"] == pytest.approx(5.00)
    assert cols["sp_fip_diff"] == pytest.approx(3.10 - 5.00)
    assert cols["sp_fip_diff"] != pytest.approx(0.0)


@patch("gametime.pregame.baseball.models.pitcher.fetch_probable_pitchers")
def test_latest_pitcher_columns_stable_without_new_starts(mock_fetch):
    games, pitcher_games = _games_and_sidecar()
    mock_fetch.return_value = (100, 200)
    kwargs = dict(home="AAA", away="BBB", games=games, pitcher_games=pitcher_games)
    a = latest_pitcher_columns(**kwargs, game_date=date(2024, 4, 10))
    b = latest_pitcher_columns(**kwargs, game_date=date(2024, 4, 12))
    assert a["home_sp_fip"] == b["home_sp_fip"]
    assert a["away_sp_fip"] == b["away_sp_fip"]
    assert a["sp_fip_diff"] == b["sp_fip_diff"]


def test_fip_prior_excludes_same_day_sidecar_row():
    games = pd.DataFrame(
        {
            "game_id": ["g_same"],
            "game_date": [pd.Timestamp("2024-04-10")],
            "home_team": ["AAA"],
            "away_team": ["BBB"],
        }
    )
    pitcher_games = pd.DataFrame(
        {
            "game_id": ["g_same"],
            "home_sp_id": [100],
            "away_sp_id": [200],
            "home_sp_fip": [2.50],
            "away_sp_fip": [6.00],
            "home_sp_rest_days": [5.0],
            "away_sp_rest_days": [5.0],
            "has_starting_pitcher": [1],
        }
    )
    fip, rest = fip_prior_for_pitcher_id(
        pitcher_games, games, 100, date(2024, 4, 10)
    )
    assert fip == pytest.approx(LEAGUE_FIP)
    assert rest == pytest.approx(5.0)

    fip_prior, _ = fip_prior_for_pitcher_id(
        pitcher_games, games, 100, date(2024, 4, 11)
    )
    assert fip_prior == pytest.approx(2.50)


@patch("gametime.pregame.baseball.models.pitcher.fetch_probable_pitchers")
def test_fip_prior_uses_strictly_prior_games_only(mock_fetch):
    games, pitcher_games = _games_and_sidecar()
    mock_fetch.return_value = (100, None)
    fip, _ = fip_prior_for_pitcher_id(pitcher_games, games, 100, date(2024, 4, 6))
    assert fip == pytest.approx(3.20)
