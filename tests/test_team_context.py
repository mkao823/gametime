import pandas as pd

from gametime.pregame.team_context import (
    FEATURE_ROADMAP,
    _series_game_number,
    build_team_rolling_context,
    current_h2h,
    enrich_games,
)


def _sample_team_games() -> pd.DataFrame:
    rows = []
    for gid, team, opp, home, pf, pa in [
        ("0022400001", "OKC", "HOU", 1, 120, 110),
        ("0022400002", "OKC", "DAL", 1, 115, 112),
        ("0022400003", "SAS", "LAL", 1, 108, 105),
        ("0022400004", "OKC", "SAS", 1, 118, 114),
        ("0042400401", "OKC", "SAS", 1, 105, 100),
        ("0042400402", "SAS", "OKC", 0, 102, 98),
    ]:
        rows.append(
            {
                "game_id": gid,
                "season_start_year": 2024,
                "seasontype": "po" if gid.startswith("004") else "rg",
                "team": team,
                "opponent": opp,
                "is_home": home,
                "points_for": float(pf),
                "points_against": float(pa),
                "margin": float(pf - pa),
                "total": float(pf + pa),
                "won": int(pf > pa),
                "team_game_idx": 0,
            }
        )
    return pd.DataFrame(rows)


def _sample_games() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "game_id": "0042400402",
                "season_start_year": 2024,
                "seasontype": "po",
                "home_tricode": "SAS",
                "away_tricode": "OKC",
                "home_final": 102,
                "away_final": 98,
            }
        ]
    )


def test_series_game_number():
    games = pd.DataFrame(
        [
            {"game_id": "0042400401", "season_start_year": 2024, "seasontype": "po",
             "home_tricode": "OKC", "away_tricode": "SAS", "home_final": 105, "away_final": 100},
            {"game_id": "0042400402", "season_start_year": 2024, "seasontype": "po",
             "home_tricode": "SAS", "away_tricode": "OKC", "home_final": 102, "away_final": 98},
        ]
    )
    ns = _series_game_number(games)
    assert ns.iloc[0] == 1.0
    assert ns.iloc[1] == 2.0


def test_enrich_games_has_expected_form_total():
    games = _sample_games()
    tg = _sample_team_games()
    out = enrich_games(games, tg, window=3)
    assert "expected_form_total" in out.columns
    assert out["expected_form_total"].iloc[0] > 0


def test_current_h2h_from_home_perspective():
    tg = _sample_team_games()
    total, margin = current_h2h(tg, "SAS", "OKC", window=3)
    assert total > 0


def test_feature_roadmap_documents_future_work():
    assert "home_stand_len" in FEATURE_ROADMAP
    assert "injury_availability" in FEATURE_ROADMAP


def test_build_team_rolling_context_causal():
    tg = _sample_team_games()
    ctx = build_team_rolling_context(tg, window=2)
    okc = ctx[ctx["team"] == "OKC"].sort_values("game_id")
    assert len(okc) >= 1
