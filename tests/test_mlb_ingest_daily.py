from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from gametime.ingest.mlb import build_games_table, download_mlb_games, fetch_team_season


def test_fetch_team_season_skips_unknown_run_rows():
    raw = pd.DataFrame(
        [
            {"Date": "2026-04-01", "Opp": "BOS", "Home_Away": "Home", "R": "Unknown", "RA": 2},
            {"Date": "2026-04-02", "Opp": "BOS", "Home_Away": "Home", "R": 5, "RA": 3},
        ]
    )

    fake_pybaseball = types.SimpleNamespace(
        cache=types.SimpleNamespace(enable=lambda: None),
        schedule_and_record=lambda season, team: raw,
    )
    with patch.dict(sys.modules, {"pybaseball": fake_pybaseball}):
        out = fetch_team_season("NYY", 2026, pause=0, row_heartbeat_every=0)

    assert len(out) == 1
    assert out.iloc[0]["home_runs"] == 5.0
    assert out.iloc[0]["away_runs"] == 3.0


def test_build_games_table_emits_heartbeat(capsys):
    chunk = pd.DataFrame(
        [
            {
                "game_id": "g1",
                "game_date": pd.Timestamp("2026-04-01"),
                "home_team": "NYY",
                "away_team": "BOS",
                "home_runs": 5.0,
                "away_runs": 3.0,
                "total_final": 8.0,
                "margin_final": 2.0,
                "season_start_year": 2026,
                "seasontype": "rg",
            }
        ]
    )
    with patch("gametime.ingest.mlb.fetch_team_season", return_value=chunk):
        out = build_games_table([2026], teams=["NYY", "BOS"], heartbeat_every_teams=1)
    captured = capsys.readouterr().out
    assert "[mlb] heartbeat teams=" in captured
    assert not out.empty


def test_download_mlb_games_daily_mode_skips_pybaseball_rebuild(tmp_path: Path):
    games_path = tmp_path / "games.parquet"
    existing = pd.DataFrame(
        [
            {
                "game_id": "g1",
                "game_date": pd.Timestamp("2026-04-01"),
                "home_team": "NYY",
                "away_team": "BOS",
                "home_runs": 4.0,
                "away_runs": 2.0,
                "total_final": 6.0,
                "margin_final": 2.0,
                "season_start_year": 2026,
                "seasontype": "rg",
            }
        ]
    )
    existing.to_parquet(games_path, index=False)

    merged = existing.copy()
    with patch(
        "gametime.ingest.mlb.build_games_table",
        side_effect=AssertionError("daily mode should not call build_games_table"),
    ), patch(
        "gametime.ingest.mlb_statsapi_games.merge_statsapi_into_games",
        return_value=merged,
    ) as mock_merge:
        out = download_mlb_games(
            games_path,
            seasons=[2026],
            mode="daily",
            statsapi_backfill_days=7,
        )

    assert out == games_path
    assert mock_merge.called
    written = pd.read_parquet(games_path)
    assert len(written) == 1
    assert written.iloc[0]["game_id"] == "g1"
