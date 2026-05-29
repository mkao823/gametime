"""Tests for retro MLB pregame slate backtest (no full model artifacts)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from gametime.pregame.baseball.slate_backtest import (
    aggregate_daily_metrics,
    discover_slate_dates,
    run_slate_backtest_day,
    slate_actuals_for_date,
    write_games_through,
)


def _synthetic_games() -> pd.DataFrame:
    """Three consecutive RS days: AAA home vs BBB."""
    dates = pd.date_range("2024-06-01", periods=3, freq="D")
    return pd.DataFrame(
        {
            "game_id": ["g1", "g2", "g3"],
            "game_date": dates,
            "home_team": ["AAA", "AAA", "AAA"],
            "away_team": ["BBB", "BBB", "BBB"],
            "home_runs": [5, 4, 3],
            "away_runs": [3, 4, 5],
            "margin_final": [2, 0, -2],
            "total_final": [8.0, 8.0, 8.0],
            "season_start_year": [2024, 2024, 2024],
            "seasontype": ["rg", "rg", "rg"],
        }
    )


class _MockPredictor:
    def predict(self, *, home: str, away: str, is_playoff: bool = False):
        from types import SimpleNamespace

        return SimpleNamespace(
            pred_total=10.0,
            pred_margin=1.0,
            winner_tricode=home,
        )


def _mock_factory(*_args, **_kwargs):
    return _MockPredictor()


def test_discover_slate_dates_window():
    games = _synthetic_games()
    found = discover_slate_dates(
        games, end_date=date(2024, 6, 3), days=14, regular_season_only=True
    )
    assert found == [date(2024, 6, 1), date(2024, 6, 2), date(2024, 6, 3)]


def test_write_games_through_excludes_slate_day(tmp_path: Path):
    games = _synthetic_games()
    slate = date(2024, 6, 2)
    out = tmp_path / "games_through_2024-06-02.parquet"
    write_games_through(games, slate, out)
    prior = pd.read_parquet(out)
    assert prior["game_date"].max().date() == date(2024, 6, 1)
    assert (prior["game_date"].dt.date < slate).all()


def test_slate_actuals_empty_for_off_day():
    games = _synthetic_games()
    actuals = slate_actuals_for_date(games, date(2024, 6, 10), regular_season_only=True)
    assert actuals.empty


def test_run_slate_backtest_day_skips_empty_slate(tmp_path: Path):
    games = _synthetic_games()
    game_df, daily = run_slate_backtest_day(
        games,
        date(2024, 6, 10),
        model_dir=tmp_path,
        games_through_dir=tmp_path,
        form_window=10,
        runs_strength_window=30,
        train_seasons=[2024],
        train_seasontypes=["rg"],
        use_stacking=False,
        elo_params=None,
        pitcher_games_path=None,
        park_factors_path=None,
        league_total_fallback=8.5,
        h2h_window=10,
        h2h_shrink_k=8.0,
        predictor_factory=_mock_factory,
    )
    assert game_df.empty
    assert daily == {}


def test_run_slate_backtest_day_mae_and_winner(tmp_path: Path):
    games = _synthetic_games()
    game_df, daily = run_slate_backtest_day(
        games,
        date(2024, 6, 2),
        model_dir=tmp_path,
        games_through_dir=tmp_path,
        form_window=10,
        runs_strength_window=30,
        train_seasons=[2024],
        train_seasontypes=["rg"],
        use_stacking=False,
        elo_params=None,
        pitcher_games_path=None,
        park_factors_path=None,
        league_total_fallback=8.5,
        h2h_window=10,
        h2h_shrink_k=8.0,
        predictor_factory=_mock_factory,
    )
    assert len(game_df) == 1
    row = game_df.iloc[0]
    assert row["total_err"] == pytest.approx(2.0)  # pred 10 - actual 8
    assert row["margin_err"] == pytest.approx(1.0)  # pred 1 - actual 0
    assert bool(row["winner_ok"])
    assert daily["total_mae"] == pytest.approx(2.0)
    assert daily["margin_mae"] == pytest.approx(1.0)
    assert daily["winner_accuracy"] == pytest.approx(1.0)
    assert daily["bias_total"] == pytest.approx(2.0)


def test_aggregate_daily_metrics_empty():
    assert aggregate_daily_metrics(pd.DataFrame(), slate_date=date(2024, 6, 1), blend_mode="linear") == {}


def test_day2_history_does_not_include_day2_runs(tmp_path: Path):
    """Day-2 preds must not see day-2 results in truncated games parquet."""
    games = _synthetic_games()
    slate = date(2024, 6, 2)
    out = tmp_path / f"games_through_{slate.isoformat()}.parquet"
    write_games_through(games, slate, out)
    prior = pd.read_parquet(out)
    assert "g2" not in set(prior["game_id"])
    assert prior.loc[prior["game_id"] == "g1", "home_runs"].iloc[0] == 5
