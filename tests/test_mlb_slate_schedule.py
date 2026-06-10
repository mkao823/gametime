"""Slate matchup ordering by MLB Stats API start times."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pandas as pd

from gametime.ingest.mlb import slate_matchups_for_date


def test_slate_matchups_sorted_by_start_time(tmp_path):
    games = pd.DataFrame(
        {
            "game_id": ["g1", "g2", "g3"],
            "game_date": [pd.Timestamp("2024-06-15")] * 3,
            "home_team": ["NYY", "CHC", "LAD"],
            "away_team": ["BOS", "STL", "SFG"],
            "seasontype": ["rg", "rg", "rg"],
            "season_start_year": [2024, 2024, 2024],
        }
    )
    games_path = tmp_path / "games.parquet"
    games.to_parquet(games_path)

    schedule_times = {
        ("BOS", "NYY"): "2024-06-15T17:05:00Z",
        ("STL", "CHC"): "2024-06-15T23:15:00Z",
        ("SFG", "LAD"): "2024-06-15T20:10:00Z",
    }

    with patch(
        "gametime.ingest.mlb_schedule.fetch_slate_times_for_date",
        return_value=schedule_times,
    ):
        matchups = slate_matchups_for_date(
            date(2024, 6, 15),
            games_path=games_path,
            regular_season_only=True,
        )

    assert [m["away"] for m in matchups] == ["BOS", "SFG", "STL"]
    assert matchups[0]["start_time"] == "2024-06-15T17:05:00Z"
    assert matchups[1]["start_time"] == "2024-06-15T20:10:00Z"
    assert matchups[2]["start_time"] == "2024-06-15T23:15:00Z"


def test_slate_matchups_missing_time_sorts_after_timed(tmp_path):
    games = pd.DataFrame(
        {
            "game_id": ["g1", "g2"],
            "game_date": [pd.Timestamp("2024-06-15")] * 2,
            "home_team": ["NYY", "CHC"],
            "away_team": ["BOS", "STL"],
            "seasontype": ["rg", "rg"],
            "season_start_year": [2024, 2024],
        }
    )
    games_path = tmp_path / "games.parquet"
    games.to_parquet(games_path)

    schedule_times = {
        ("BOS", "NYY"): "2024-06-15T17:05:00Z",
    }

    with patch(
        "gametime.ingest.mlb_schedule.fetch_slate_times_for_date",
        return_value=schedule_times,
    ):
        matchups = slate_matchups_for_date(
            date(2024, 6, 15),
            games_path=games_path,
            regular_season_only=True,
        )

    assert matchups[0]["away"] == "BOS"
    assert matchups[0]["start_time"] == "2024-06-15T17:05:00Z"
    assert matchups[1]["away"] == "STL"
    assert matchups[1]["start_time"] is None
