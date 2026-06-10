"""Predictions API v1 — TestClient with mocked predictor (no network)."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from gametime.api.app import create_app
from gametime.api.deps import AppSettings, AppState
from gametime.pregame.baseball.predict import BaseballPregamePrediction


def _sample_prediction(
    home: str = "NYY",
    away: str = "BOS",
    *,
    is_playoff: bool = False,
) -> BaseballPregamePrediction:
    return BaseballPregamePrediction(
        home_tricode=home,
        away_tricode=away,
        variant="ensemble",
        is_playoff=is_playoff,
        pred_total=8.5,
        pred_margin=0.3,
        pred_home_final=4.4,
        pred_away_final=4.1,
        winner_tricode=home,
        win_prob_home=0.55,
        home_form_n=10,
        away_form_n=10,
        member_totals={"lgbm": 8.2, "heuristic": 8.8},
        member_margins={"lgbm": 0.1, "heuristic": 0.5},
    )


def _test_state(
    tmp_path: Path,
    *,
    games_df: pd.DataFrame | None = None,
) -> AppState:
    root = tmp_path
    config_path = root / "configs" / "mlb.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("sport: mlb\n")

    games_path = root / "data" / "mlb" / "processed" / "games.parquet"
    games_path.parent.mkdir(parents=True, exist_ok=True)
    if games_df is None:
        games_df = pd.DataFrame(
            {
                "game_id": ["g1"],
                "game_date": [pd.Timestamp("2024-06-15")],
                "home_team": ["NYY"],
                "away_team": ["BOS"],
                "seasontype": ["rg"],
                "season_start_year": [2024],
            }
        )
    games_df.to_parquet(games_path)

    predictor = MagicMock()
    predictor.games = games_df
    predictor.ensemble_cfg = {"members": ["lgbm", "heuristic"]}
    predictor.model_dir = root / "models" / "mlb" / "pregame"
    predictor.predict.return_value = _sample_prediction()

    settings = AppSettings(root=root, config_path=config_path, cfg={"sport": "mlb"})
    from gametime.sports import MLB

    return AppState(
        settings=settings,
        predictor=predictor,
        model_dir=root / "models" / "mlb" / "pregame",
        games_path=games_path,
        mlb_teams=frozenset(MLB.mlb_teams),
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    games = pd.DataFrame(
        {
            "game_id": ["g1"],
            "game_date": [pd.Timestamp("2024-06-15")],
            "home_team": ["NYY"],
            "away_team": ["BOS"],
            "seasontype": ["rg"],
            "season_start_year": [2024],
        }
    )
    state = _test_state(tmp_path, games_df=games)

    monkeypatch.setattr(
        "gametime.api.app.slate_for_date",
        lambda gt, slate_date, *, regular_season: (
            [{"game_id": "g1", "home": "NYY", "away": "BOS"}]
            if slate_date == date(2024, 6, 15) and regular_season
            else []
        ),
    )
    monkeypatch.setattr(
        "gametime.api.app.matchup_on_slate",
        lambda gt, *, home, away, slate_date, regular_season: (
            home == "NYY"
            and away == "BOS"
            and slate_date == date(2024, 6, 15)
            and regular_season
        ),
    )

    with TestClient(create_app(state=state)) as tc:
        yield tc


def test_health_shape(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["games_max_date"] == "2024-06-15"
    assert body["model_dir"] == "models/mlb/pregame"
    assert body["ensemble_members"] == ["lgbm", "heuristic"]


def test_slate_empty(client, monkeypatch):
    monkeypatch.setattr(
        "gametime.api.app.slate_for_date",
        lambda *args, **kwargs: [],
    )
    resp = client.get("/v1/slate?date=2024-06-15")
    assert resp.status_code == 200
    body = resp.json()
    assert body["date"] == "2024-06-15"
    assert body["season_start_year"] == 2024
    assert body["games"] == []


def test_game_happy_path(client):
    resp = client.get("/v1/game?home=NYY&away=BOS&date=2024-06-15")
    assert resp.status_code == 200
    body = resp.json()
    assert body["home"] == "NYY"
    assert body["away"] == "BOS"
    assert body["date"] == "2024-06-15"
    assert body["pred_total"] == 8.5
    assert body["winner"] == "NYY"
    assert "member_totals" not in body


def test_game_include_members(client):
    resp = client.get(
        "/v1/game?home=NYY&away=BOS&date=2024-06-15&include_members=true"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["member_totals"]["lgbm"] == 8.2
    assert body["member_margins"]["heuristic"] == 0.5


def test_invalid_tricode_422(client):
    resp = client.get("/v1/game?home=NEWYORK&away=BOS&date=2024-06-15")
    assert resp.status_code == 422


def test_unknown_tricode_422(client):
    resp = client.get("/v1/game?home=ZZZ&away=BOS&date=2024-06-15")
    assert resp.status_code == 422


def test_game_not_on_slate_404(client):
    resp = client.get("/v1/game?home=CHC&away=STL&date=2024-06-15")
    assert resp.status_code == 404


def test_slate_start_time_and_order(client, monkeypatch):
    monkeypatch.setattr(
        "gametime.api.app.slate_for_date",
        lambda gt, slate_date, *, regular_season: [
            {
                "game_id": "g1",
                "home": "NYY",
                "away": "BOS",
                "start_time": "2024-06-15T17:05:00Z",
            },
            {
                "game_id": "g2",
                "home": "LAD",
                "away": "SFG",
                "start_time": "2024-06-15T20:10:00Z",
            },
        ],
    )

    def _predict_side_effect(*, home, away, is_playoff, game_date):
        return _sample_prediction(home=home, away=away, is_playoff=is_playoff)

    client.app.state.gt.predictor.predict.side_effect = _predict_side_effect

    resp = client.get("/v1/slate?date=2024-06-15")
    assert resp.status_code == 200
    games = resp.json()["games"]
    assert len(games) == 2
    assert games[0]["away"] == "BOS"
    assert games[0]["start_time"] == "2024-06-15T17:05:00Z"
    assert games[1]["away"] == "SFG"
    assert games[1]["start_time"] == "2024-06-15T20:10:00Z"
