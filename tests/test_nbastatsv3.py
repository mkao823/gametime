from gametime.data.nbastatsv3 import parse_v3_clock, tricode_and_finals_from_v3


def test_parse_v3_clock():
    assert parse_v3_clock("PT12M00.00S") == 720.0
    assert parse_v3_clock("PT11M26.00S") == 686.0
    assert parse_v3_clock("") is None


def test_tricode_and_finals_from_v3():
    import pandas as pd

    raw = pd.DataFrame(
        {
            "gameId": [22500001, 22500001, 22500001],
            "actionNumber": [1, 2, 3],
            "location": ["h", "v", "h"],
            "teamTricode": ["OKC", "HOU", "OKC"],
            "scoreHome": [0.0, 2.0, 5.0],
            "scoreAway": [0.0, 0.0, 2.0],
        }
    )
    games = tricode_and_finals_from_v3(raw)
    assert len(games) == 1
    assert games.iloc[0]["home_tricode"] == "OKC"
    assert games.iloc[0]["away_tricode"] == "HOU"
    assert games.iloc[0]["home_final"] == 5.0
    assert games.iloc[0]["away_final"] == 2.0
