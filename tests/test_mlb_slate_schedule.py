"""Slate matchup ordering by MLB Stats API start times."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

from gametime.ingest.mlb import fetch_slate_from_statsapi, slate_matchups_for_date
from gametime.ingest.mlb_schedule import fetch_slate_schedule_for_date


def _schedule_payload(games: list[dict]) -> dict:
    return {"dates": [{"games": games}]}


def _game(
    game_pk: int,
    away: str,
    home: str,
    start: str,
    *,
    state: str = "Preview",
) -> dict:
    return {
        "gamePk": game_pk,
        "gameDate": start,
        "status": {"abstractGameState": state},
        "teams": {
            "away": {"team": {"abbreviation": away}},
            "home": {"team": {"abbreviation": home}},
        },
    }


def test_fetch_slate_schedule_excludes_postponed():
    fetch_slate_schedule_for_date.cache_clear()
    payload = _schedule_payload(
        [
            _game(1, "BOS", "NYY", "2024-06-15T17:05:00Z"),
            _game(2, "STL", "CHC", "2024-06-15T20:05:00Z", state="Postponed"),
        ]
    )
    with patch("gametime.ingest.mlb_schedule._http_json", return_value=payload):
        rows = fetch_slate_schedule_for_date(date(2024, 6, 15))
    assert len(rows) == 1
    assert rows[0]["away"] == "BOS"
    assert rows[0]["game_id"] == "1"


def test_slate_matchups_from_statsapi_sorted_by_start_time():
    schedule_rows = [
        {
            "game_id": "3",
            "away": "STL",
            "home": "CHC",
            "start_time": "2024-06-15T23:15:00Z",
        },
        {
            "game_id": "1",
            "away": "BOS",
            "home": "NYY",
            "start_time": "2024-06-15T17:05:00Z",
        },
        {
            "game_id": "2",
            "away": "SFG",
            "home": "LAD",
            "start_time": "2024-06-15T20:10:00Z",
        },
    ]
    with patch(
        "gametime.ingest.mlb.fetch_slate_from_statsapi",
        return_value=schedule_rows,
    ):
        matchups = slate_matchups_for_date(date(2024, 6, 15), regular_season_only=True)

    assert [m["away"] for m in matchups] == ["BOS", "SFG", "STL"]
    assert matchups[0]["start_time"] == "2024-06-15T17:05:00Z"
    assert matchups[1]["start_time"] == "2024-06-15T20:10:00Z"
    assert matchups[2]["start_time"] == "2024-06-15T23:15:00Z"


def test_statsapi_success_skips_pybaseball(tmp_path):
    schedule_rows = [
        {
            "game_id": "1",
            "away": "BOS",
            "home": "NYY",
            "start_time": "2024-06-15T17:05:00Z",
        },
    ]
    pybaseball_mock = MagicMock()
    with patch(
        "gametime.ingest.mlb.fetch_slate_from_statsapi",
        return_value=schedule_rows,
    ), patch(
        "gametime.ingest.mlb.fetch_slate_from_pybaseball",
        pybaseball_mock,
    ):
        matchups = slate_matchups_for_date(date(2024, 6, 15), regular_season_only=True)

    pybaseball_mock.assert_not_called()
    assert len(matchups) == 1
    assert matchups[0]["away"] == "BOS"


def test_statsapi_failure_falls_back_to_pybaseball():
    pybaseball_rows = [
        {"game_id": "g1", "away": "BOS", "home": "NYY"},
    ]
    schedule_times = {("BOS", "NYY"): "2024-06-15T17:05:00Z"}
    with patch(
        "gametime.ingest.mlb.fetch_slate_from_statsapi",
        side_effect=RuntimeError("network"),
    ), patch(
        "gametime.ingest.mlb.fetch_slate_from_pybaseball",
        return_value=pybaseball_rows,
    ) as py_mock, patch(
        "gametime.ingest.mlb_schedule.fetch_slate_times_for_date",
        return_value=schedule_times,
    ):
        matchups = slate_matchups_for_date(date(2024, 6, 15), regular_season_only=True)

    py_mock.assert_called_once()
    assert matchups[0]["away"] == "BOS"
    assert matchups[0]["start_time"] == "2024-06-15T17:05:00Z"


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


def test_fetch_slate_from_statsapi_maps_schedule_rows():
    schedule_rows = [
        {
            "game_id": "99",
            "away": "BOS",
            "home": "NYY",
            "start_time": "2024-06-15T17:05:00Z",
        },
    ]
    with patch(
        "gametime.ingest.mlb_schedule.fetch_slate_schedule_for_date",
        return_value=schedule_rows,
    ):
        rows = fetch_slate_from_statsapi(date(2024, 6, 15))
    assert rows == schedule_rows
