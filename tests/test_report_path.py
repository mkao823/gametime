from pathlib import Path

from gametime.live.report_path import resolve_live_json_path


def test_resolve_inserts_date_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "gametime.live.report_path.fetch_todays_scoreboard",
        lambda: {"scoreboard": {"gameDate": "2026-05-25"}},
    )
    monkeypatch.setattr(
        "gametime.live.report_path.find_game",
        lambda **kw: type("S", (), {"away_tricode": "NYK", "home_tricode": "CLE"})(),
    )
    path = resolve_live_json_path(
        tmp_path,
        json_out="reports/live_nyk_cle.json",
        home="CLE",
        away="NYK",
    )
    assert path is not None
    assert "20260525" in path.name
    assert path.name.endswith(".json")
