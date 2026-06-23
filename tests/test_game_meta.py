from __future__ import annotations

import pandas as pd

from gametime.data.game_meta import annotate_games, filter_games


def test_annotate_games_derives_common_columns():
    df = pd.DataFrame(
        {
            "game_id": ["0022400001", "0042400001"],
        }
    )
    out = annotate_games(df)
    assert "season_start_year" in out.columns
    assert "seasontype" in out.columns
    assert int(out.loc[0, "season_start_year"]) == 2024
    assert out.loc[0, "seasontype"] == "rg"
    assert out.loc[1, "seasontype"] == "po"


def test_filter_games_applies_season_and_type():
    df = pd.DataFrame(
        {
            "game_id": ["g1", "g2", "g3"],
            "season_start_year": [2023, 2024, 2024],
            "seasontype": ["rg", "rg", "po"],
        }
    )
    out = filter_games(df, seasons=[2024], seasontypes=["rg"])
    assert list(out["game_id"]) == ["g2"]

from gametime.data.game_meta import seasontype_from_game_id, season_start_year


def test_playoff_id():
    assert seasontype_from_game_id("0042500314") == "po"
    assert seasontype_from_game_id("0022400928") == "rg"
    assert season_start_year("0022400928") == 2024


def test_wnba_game_ids():
    from gametime.sports import WNBA

    assert seasontype_from_game_id("1022400001", league=WNBA) == "rg"
    assert seasontype_from_game_id("1042400101", league=WNBA) == "po"
    assert season_start_year("1022400001") == 2024


def test_filter_games_preserves_wnba_seasontype():
    import pandas as pd
    from gametime.data.game_meta import filter_games

    df = pd.DataFrame(
        {"game_id": ["1022400001"], "season_start_year": [2024], "seasontype": ["rg"]}
    )
    out = filter_games(df, seasons=[2024], seasontypes=["rg"])
    assert len(out) == 1
