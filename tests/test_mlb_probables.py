"""MLB schedule probable SP fetch and slate labels."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from gametime.ingest.mlb_pitchers import (
    ProbablePitcher,
    fetch_probable_pitchers,
    fetch_probables_for_date,
    format_probable_sp_line,
    lookup_probables_for_matchup,
    pitcher_short_label,
)


def test_pitcher_short_label_and_matchup_format():
    assert pitcher_short_label(ProbablePitcher(1, "Ranger Suarez")) == "Suarez"
    assert pitcher_short_label(None) == "—"
    away = ProbablePitcher(1, "Ranger Suarez")
    home = ProbablePitcher(2, "Tanner Bibee")
    assert format_probable_sp_line(away, home) == "Suarez @ Bibee"


def test_lookup_probables_for_matchup_athletics_alias():
    probables = {
        ("OAK", "NYY"): (
            ProbablePitcher(10, "Home Pitcher"),
            ProbablePitcher(20, "Away Pitcher"),
        ),
    }
    home_pp, away_pp = lookup_probables_for_matchup(probables, "ATH", "NYY")
    assert home_pp is not None and home_pp.full_name == "Home Pitcher"
    assert away_pp is not None and away_pp.full_name == "Away Pitcher"


@patch("gametime.ingest.mlb_pitchers._http_json")
def test_fetch_probables_requires_team_hydrate(mock_http):
    fetch_probables_for_date.cache_clear()
    mock_http.return_value = {
        "dates": [
            {
                "games": [
                    {
                        "teams": {
                            "home": {
                                "team": {"abbreviation": "BAL"},
                                "probablePitcher": {"id": 1, "fullName": "Kyle Bradish"},
                            },
                            "away": {
                                "team": {"abbreviation": "TOR"},
                                "probablePitcher": {"id": 2, "fullName": "Kevin Gausman"},
                            },
                        },
                    }
                ]
            }
        ]
    }
    probables = fetch_probables_for_date(date(2026, 5, 31))
    assert ("BAL", "TOR") in probables
    home_pp, away_pp = probables[("BAL", "TOR")]
    assert home_pp.full_name == "Kyle Bradish"
    assert away_pp.full_name == "Kevin Gausman"
    assert fetch_probable_pitchers(date(2026, 5, 31), "BAL", "TOR") == (1, 2)
    url = mock_http.call_args[0][0]
    assert "probablePitcher,team" in url
