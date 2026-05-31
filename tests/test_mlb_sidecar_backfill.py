"""W10 historical SP + lineup sidecar backfill tests (no network)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from gametime.ingest.mlb_lineup import (
    LEAGUE_WOBA,
    _PlayerBatCum,
    _apply_box_to_cum,
    _side_lineup_woba_prior,
    build_lineup_games_table,
)
from gametime.ingest.mlb_pitchers import (
    LEAGUE_FIP,
    _PitcherCumStats,
    build_pitcher_games_table,
)
from gametime.pipeline import _sidecar_needs_train_backfill, _sidecar_train_coverage_frac
from gametime.pregame.baseball.models.lineup import attach_lineup
from gametime.pregame.baseball.models.pitcher import attach_pitcher


def _sample_games() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "game_id": ["g2021", "g2022", "g2023", "g2024"],
            "game_date": pd.to_datetime(
                ["2021-06-01", "2022-06-01", "2023-06-01", "2024-06-01"]
            ),
            "home_team": ["NYY", "NYY", "NYY", "NYY"],
            "away_team": ["BOS", "BOS", "BOS", "BOS"],
            "home_runs": [4, 5, 3, 6],
            "away_runs": [3, 2, 4, 5],
            "season_start_year": [2021, 2022, 2023, 2024],
            "seasontype": ["rg", "rg", "rg", "rg"],
        }
    )


def _boxscore(
    *,
    home_sp: int = 101,
    away_sp: int = 201,
    home_batters: list[int] | None = None,
    away_batters: list[int] | None = None,
) -> dict:
    home_batters = home_batters or list(range(301, 310))
    away_batters = away_batters or list(range(401, 410))

    def _batters(ids: list[int]) -> dict:
        out: dict = {}
        for i, pid in enumerate(ids):
            out[f"ID{pid}"] = {
                "person": {"id": pid},
                "battingOrder": str(i + 1),
                "stats": {
                    "batting": {
                        "atBats": 4,
                        "hits": 1,
                        "doubles": 0,
                        "triples": 0,
                        "homeRuns": 0,
                        "baseOnBalls": 0,
                        "hitByPitch": 0,
                        "sacFlies": 0,
                    }
                },
            }
        return out

    def _starter(sp_id: int) -> dict:
        return {
            f"ID{sp_id}": {
                "person": {"id": sp_id},
                "stats": {
                    "pitching": {
                        "gamesStarted": 1,
                        "inningsPitched": "6.0",
                        "homeRuns": 1,
                        "baseOnBalls": 2,
                        "hitByPitch": 0,
                        "strikeOuts": 5,
                    }
                },
            }
        }

    home_players = {**_batters(home_batters), **_starter(home_sp)}
    away_players = {**_batters(away_batters), **_starter(away_sp)}
    return {"teams": {"home": {"players": home_players}, "away": {"players": away_players}}}


def test_build_pitcher_table_includes_2021_when_min_season_2021(tmp_path: Path):
    games = _sample_games()
    cache_dir = tmp_path / "boxscores"
    cache_dir.mkdir()
    box = _boxscore()

    def fake_schedule(day):
        return [
            {
                "game_pk": 9000 + day.month,
                "game_date": pd.Timestamp(day).normalize(),
                "home_team": "NYY",
                "away_team": "BOS",
            }
        ]

    with patch(
        "gametime.ingest.mlb_pitchers.fetch_schedule_games", side_effect=fake_schedule
    ), patch(
        "gametime.ingest.mlb_pitchers._load_cached_boxscore",
        return_value=box,
    ):
        table = build_pitcher_games_table(games, min_season=2021, cache_dir=cache_dir)

    assert len(table) >= 1
    assert "g2021" in set(table["game_id"])
    assert (table["has_starting_pitcher"] == 1).all()


def test_build_lineup_table_includes_2021_when_min_season_2021(tmp_path: Path):
    games = _sample_games()
    cache_dir = tmp_path / "boxscores"
    cache_dir.mkdir()
    box = _boxscore()

    def fake_schedule(day):
        return [
            {
                "game_pk": 8000 + day.month,
                "game_date": pd.Timestamp(day).normalize(),
                "home_team": "NYY",
                "away_team": "BOS",
            }
        ]

    with patch(
        "gametime.ingest.mlb_lineup.fetch_schedule_games", side_effect=fake_schedule
    ), patch(
        "gametime.ingest.mlb_lineup._load_cached_boxscore",
        return_value=box,
    ):
        table = build_lineup_games_table(games, min_season=2021, boxscore_cache_dir=cache_dir)

    row_2021 = table[table["game_id"] == "g2021"].iloc[0]
    assert int(row_2021["has_lineup"]) == 1
    assert row_2021["home_lineup_woba"] == pytest.approx(LEAGUE_WOBA)


def test_attach_sidecars_set_has_flags_on_train_era_games():
    games = _sample_games()
    pitcher_games = pd.DataFrame(
        {
            "game_id": ["g2021", "g2022"],
            "home_sp_id": [101, 101],
            "away_sp_id": [201, 201],
            "home_sp_fip": [3.50, 3.40],
            "away_sp_fip": [4.10, 4.00],
            "home_sp_rest_days": [5.0, 5.0],
            "away_sp_rest_days": [5.0, 5.0],
            "has_starting_pitcher": [1, 1],
        }
    )
    lineup_games = pd.DataFrame(
        {
            "game_id": ["g2021", "g2022"],
            "home_lineup_woba": [0.330, 0.325],
            "away_lineup_woba": [0.310, 0.315],
            "lineup_platoon_diff": [0.02, 0.01],
            "has_lineup": [1, 1],
        }
    )
    table = attach_pitcher(games, pitcher_games)
    table = attach_lineup(table, lineup_games)

    train = table[table["season_start_year"].isin([2021, 2022, 2023])]
    assert (train.loc[train["game_id"].isin(["g2021", "g2022"]), "has_starting_pitcher"] == 1).all()
    assert (train.loc[train["game_id"].isin(["g2021", "g2022"]), "has_lineup"] == 1).all()
    assert int(train.loc[train["game_id"] == "g2023", "has_lineup"].iloc[0]) == 0


def test_cumulative_fip_uses_prior_games_only():
    cum = _PitcherCumStats()
    d1 = pd.Timestamp("2021-04-01")
    d2 = pd.Timestamp("2021-04-08")
    assert cum.fip_prior() == pytest.approx(LEAGUE_FIP)
    pre_game_fip_g2 = cum.fip_prior()
    cum.apply_game_line(ip=6.0, hr=1, bb=2, hbp=0, so=5, game_date=d1)
    assert pre_game_fip_g2 == pytest.approx(LEAGUE_FIP)
    pre_game_fip_g3 = cum.fip_prior()
    assert pre_game_fip_g3 != pytest.approx(LEAGUE_FIP)
    cum.apply_game_line(ip=5.0, hr=0, bb=1, hbp=0, so=4, game_date=d2)
    assert cum.fip_prior() != pytest.approx(pre_game_fip_g3)


def test_cumulative_woba_uses_prior_plate_appearances_only():
    box1 = _boxscore(home_batters=[501, 502, 503, 504, 505])
    box2 = _boxscore(home_batters=[501, 502, 503, 504, 505])
    cum: dict[int, _PlayerBatCum] = {}
    woba_g1 = _side_lineup_woba_prior(box1, "home", cum)
    assert woba_g1 == pytest.approx(LEAGUE_WOBA)
    _apply_box_to_cum(box1, cum)
    woba_g2 = _side_lineup_woba_prior(box2, "home", cum)
    assert woba_g2 != pytest.approx(LEAGUE_WOBA)


def test_sidecar_backfill_gate_detects_zero_train_coverage(tmp_path: Path):
    games_path = tmp_path / "games.parquet"
    sidecar_path = tmp_path / "sidecar.parquet"
    games = _sample_games()
    games.to_parquet(games_path, index=False)
    pd.DataFrame(
        {
            "game_id": games["game_id"],
            "has_lineup": [0, 0, 0, 1],
        }
    ).to_parquet(sidecar_path, index=False)

    frac = _sidecar_train_coverage_frac(
        games_path, sidecar_path, [2021, 2022, 2023], "has_lineup"
    )
    assert frac == pytest.approx(0.0)
    assert _sidecar_needs_train_backfill(
        games_path, sidecar_path, [2021, 2022, 2023], "has_lineup", min_frac=0.85
    )
