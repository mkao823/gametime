"""Tests for MLB Stats API hybrid games ingest (W6-statsapi-games)."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pandas as pd

from gametime.ingest.mlb import _game_id
from gametime.ingest.mlb_statsapi_games import (
    backfill_games_from_statsapi,
    fetch_final_games_for_date,
    merge_statsapi_into_games,
    seasontype_for_game_type,
)


def _schedule_payload(game_pk: int, game_type: str = "R") -> dict:
    return {
        "dates": [
            {
                "games": [
                    {
                        "gamePk": game_pk,
                        "gameType": game_type,
                        "status": {"abstractGameState": "Final"},
                        "teams": {
                            "home": {"team": {"abbreviation": "NYY"}},
                            "away": {"team": {"abbreviation": "BOS"}},
                        },
                    }
                ]
            }
        ]
    }


def _linescore_payload(home_runs: int, away_runs: int) -> dict:
    return {
        "teams": {
            "home": {"runs": home_runs},
            "away": {"runs": away_runs},
        }
    }


def test_seasontype_mapping():
    assert seasontype_for_game_type("R") == "rg"
    for code in ("P", "F", "W", "D", "L"):
        assert seasontype_for_game_type(code) == "po"


@patch("gametime.ingest.mlb_statsapi_games._http_json")
def test_fetch_final_games_for_date_schema(mock_http):
    game_date = date(2025, 5, 28)
    game_pk = 777001

    def fake_http(url: str) -> dict:
        if "linescore" in url:
            return _linescore_payload(5, 3)
        return _schedule_payload(game_pk, "R")

    mock_http.side_effect = fake_http

    rows = fetch_final_games_for_date(game_date, game_types=("R",), pause=0)
    assert len(rows) == 1
    row = rows[0]
    ts = pd.Timestamp(game_date).normalize()
    expected_gid = _game_id(ts, "NYY", "BOS")
    assert row["game_id"] == expected_gid
    assert row["home_team"] == "NYY"
    assert row["away_team"] == "BOS"
    assert row["home_runs"] == 5
    assert row["away_runs"] == 3
    assert row["total_final"] == 8
    assert row["margin_final"] == 2
    assert row["seasontype"] == "rg"
    assert row["season_start_year"] == 2025


@patch("gametime.ingest.mlb_statsapi_games._http_json")
def test_fetch_skips_non_final(mock_http):
    mock_http.return_value = {
        "dates": [
            {
                "games": [
                    {
                        "gamePk": 1,
                        "gameType": "R",
                        "status": {"abstractGameState": "Live"},
                        "teams": {
                            "home": {"team": {"abbreviation": "NYY"}},
                            "away": {"team": {"abbreviation": "BOS"}},
                        },
                    }
                ]
            }
        ]
    }
    rows = fetch_final_games_for_date(date(2025, 5, 28), pause=0)
    assert rows == []


@patch("gametime.ingest.mlb_statsapi_games.fetch_final_games_for_date")
def test_backfill_dedupes_game_id(mock_fetch):
    game_date = date(2025, 5, 28)
    ts = pd.Timestamp(game_date).normalize()
    gid = _game_id(ts, "NYY", "BOS")
    row = {
        "game_id": gid,
        "game_date": ts,
        "home_team": "NYY",
        "away_team": "BOS",
        "home_runs": 4,
        "away_runs": 2,
        "total_final": 6,
        "margin_final": 2,
        "season_start_year": 2025,
        "seasontype": "rg",
    }
    mock_fetch.return_value = [row, {**row, "home_runs": 5, "total_final": 7}]

    df = backfill_games_from_statsapi(
        None,
        start_date=game_date,
        end_date=game_date,
        pause=0,
    )
    assert len(df) == 1
    assert df.iloc[0]["home_runs"] == 5


@patch("gametime.ingest.mlb_statsapi_games.backfill_games_from_statsapi")
def test_merge_statsapi_prefers_api_on_duplicate(mock_backfill):
    """Stats API row replaces stale pybaseball row for same game_id."""
    game_date = pd.Timestamp("2025-05-27").normalize()
    gid = _game_id(game_date, "NYY", "BOS")
    pybaseball = pd.DataFrame(
        [
            {
                "game_id": gid,
                "game_date": game_date,
                "home_team": "NYY",
                "away_team": "BOS",
                "home_runs": 0,
                "away_runs": 0,
                "total_final": 0,
                "margin_final": 0,
                "season_start_year": 2025,
                "seasontype": "rg",
            }
        ]
    )
    api_row = pd.DataFrame(
        [
            {
                "game_id": gid,
                "game_date": game_date,
                "home_team": "NYY",
                "away_team": "BOS",
                "home_runs": 6,
                "away_runs": 4,
                "total_final": 10,
                "margin_final": 2,
                "season_start_year": 2025,
                "seasontype": "rg",
            }
        ]
    )
    mock_backfill.return_value = api_row

    merged = merge_statsapi_into_games(
        pybaseball,
        backfill_days=14,
        game_types=("R",),
        end_date=date(2025, 5, 28),
        pause=0,
    )
    assert len(merged) == 1
    assert merged.iloc[0]["home_runs"] == 6
    assert merged.iloc[0]["total_final"] == 10


@patch("gametime.ingest.mlb_statsapi_games.backfill_games_from_statsapi")
def test_merge_appends_new_games(mock_backfill):
    old_date = pd.Timestamp("2025-05-26").normalize()
    new_date = pd.Timestamp("2025-05-28").normalize()
    existing = pd.DataFrame(
        [
            {
                "game_id": _game_id(old_date, "NYY", "BOS"),
                "game_date": old_date,
                "home_team": "NYY",
                "away_team": "BOS",
                "home_runs": 3,
                "away_runs": 2,
                "total_final": 5,
                "margin_final": 1,
                "season_start_year": 2025,
                "seasontype": "rg",
            }
        ]
    )
    mock_backfill.return_value = pd.DataFrame(
        [
            {
                "game_id": _game_id(new_date, "LAD", "SFG"),
                "game_date": new_date,
                "home_team": "LAD",
                "away_team": "SFG",
                "home_runs": 7,
                "away_runs": 5,
                "total_final": 12,
                "margin_final": 2,
                "season_start_year": 2025,
                "seasontype": "rg",
            }
        ]
    )

    merged = merge_statsapi_into_games(
        existing,
        backfill_days=14,
        end_date=date(2025, 5, 28),
        pause=0,
    )
    assert len(merged) == 2
    assert merged["game_date"].max().normalize() == new_date


def test_merge_empty_api_returns_unchanged():
    games = pd.DataFrame(
        [
            {
                "game_id": "abc",
                "game_date": pd.Timestamp("2025-05-01"),
                "home_team": "NYY",
                "away_team": "BOS",
                "home_runs": 1,
                "away_runs": 0,
                "total_final": 1,
                "margin_final": 1,
                "season_start_year": 2025,
                "seasontype": "rg",
            }
        ]
    )
    with patch(
        "gametime.ingest.mlb_statsapi_games.backfill_games_from_statsapi",
        return_value=pd.DataFrame(),
    ):
        out = merge_statsapi_into_games(games, end_date=date(2025, 5, 1), pause=0)
    pd.testing.assert_frame_equal(out, games)
