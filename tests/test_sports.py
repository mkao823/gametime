from gametime.sports import MLB, NBA, WNBA, get_sport


def test_capabilities():
    assert NBA.has("ingame") and NBA.has("pregame")
    assert WNBA.has("ingame")
    assert MLB.has("pregame")
    assert not MLB.has("ingame")


def test_get_sport_from_config():
    assert get_sport({"sport": "wnba"}).id == "wnba"
    assert get_sport({"league": "nba"}).id == "nba"
