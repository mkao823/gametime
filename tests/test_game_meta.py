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
