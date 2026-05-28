"""Unit tests for MLB pregame ensemble helpers (no network / MLB data)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from gametime.pregame.baseball.ensemble import (
    combine,
    combine_equal,
    fit_weights,
    fit_weights_with_metrics,
)
from gametime.pregame.baseball.models.runs_strength import attach_runs_strength
from gametime.pregame.baseball.prediction import MemberPrediction


def _member(name: str, total: list[float], margin: list[float]) -> MemberPrediction:
    return MemberPrediction(
        member=name,
        total=np.asarray(total, dtype=float),
        margin=np.asarray(margin, dtype=float),
    )


def test_combine_weighted_matches_hand_computed():
    a = _member("a", [10.0, 20.0], [1.0, 2.0])
    b = _member("b", [14.0, 16.0], [3.0, 4.0])
    weights_total = {"a": 0.25, "b": 0.75}
    weights_margin = {"a": 0.6, "b": 0.4}
    out = combine([a, b], weights_total=weights_total, weights_margin=weights_margin)

    wt_sum = 0.25 + 0.75
    wm_sum = 0.6 + 0.4
    expected_total = np.array(
        [
            (0.25 / wt_sum) * 10.0 + (0.75 / wt_sum) * 14.0,
            (0.25 / wt_sum) * 20.0 + (0.75 / wt_sum) * 16.0,
        ]
    )
    expected_margin = np.array(
        [
            (0.6 / wm_sum) * 1.0 + (0.4 / wm_sum) * 3.0,
            (0.6 / wm_sum) * 2.0 + (0.4 / wm_sum) * 4.0,
        ]
    )
    np.testing.assert_allclose(out.total, expected_total)
    np.testing.assert_allclose(out.margin, expected_margin)


def test_combine_rejects_empty_members():
    with pytest.raises(ValueError, match="at least one"):
        combine([], weights_total={"a": 1.0})


def test_combine_rejects_zero_weight_sum():
    a = _member("a", [1.0], [1.0])
    with pytest.raises(ValueError, match="positive"):
        combine([a], weights_total={"a": 0.0})


def test_combine_equal_matches_explicit_weights():
    members = [
        _member("a", [8.0, 10.0], [0.5, 1.0]),
        _member("b", [10.0, 12.0], [1.5, 2.0]),
        _member("c", [12.0, 14.0], [2.5, 3.0]),
    ]
    equal_explicit = combine(
        members,
        weights_total={"a": 1 / 3, "b": 1 / 3, "c": 1 / 3},
        weights_margin={"a": 1 / 3, "b": 1 / 3, "c": 1 / 3},
    )
    equal_helper = combine_equal(members)
    np.testing.assert_allclose(equal_helper.total, equal_explicit.total)
    np.testing.assert_allclose(equal_helper.margin, equal_explicit.margin)


def test_fit_weights_improves_or_ties_mae_vs_equal():
    actual_total = np.array([9.0, 9.0, 9.0, 9.0])
    actual_margin = np.array([1.0, -1.0, 1.0, -1.0])
    members = [
        _member("good_total", [9.0, 9.0, 9.0, 9.0], [0.0, 0.0, 0.0, 0.0]),
        _member("good_margin", [12.0, 12.0, 12.0, 12.0], [1.0, -1.0, 1.0, -1.0]),
    ]
    equal = combine_equal(members)
    equal_total_mae = float(np.mean(np.abs(equal.total - actual_total)))
    equal_margin_mae = float(np.mean(np.abs(equal.margin - actual_margin)))

    weights_total, weights_margin = fit_weights(
        members, actual_total, actual_margin, step=0.1
    )
    tuned = combine(
        members, weights_total=weights_total, weights_margin=weights_margin
    )
    tuned_total_mae = float(np.mean(np.abs(tuned.total - actual_total)))
    tuned_margin_mae = float(np.mean(np.abs(tuned.margin - actual_margin)))

    assert tuned_total_mae <= equal_total_mae + 1e-9
    assert tuned_margin_mae <= equal_margin_mae + 1e-9
    assert tuned_total_mae < equal_total_mae or tuned_margin_mae < equal_margin_mae
    assert sum(weights_total.values()) > 0
    assert sum(weights_margin.values()) > 0


def test_fit_weights_with_metrics_keys():
    actual_total = np.array([8.0, 10.0, 9.0])
    actual_margin = np.array([2.0, -1.0, 0.5])
    members = [
        _member("m1", [8.5, 9.5, 9.0], [2.0, -0.5, 0.0]),
        _member("m2", [7.5, 10.5, 9.5], [1.5, -1.5, 1.0]),
    ]
    _, _, metrics = fit_weights_with_metrics(
        members, actual_total, actual_margin, step=0.1
    )
    assert set(metrics) >= {
        "n",
        "total_mae",
        "margin_mae",
        "winner_accuracy",
        "grid_step",
    }
    assert metrics["n"] == 3.0
    assert metrics["grid_step"] == 0.1


def test_attach_runs_strength_excludes_current_game_runs():
    """Strength for game g must use only prior games (shifted rolling)."""
    dates = pd.date_range("2024-04-01", periods=6, freq="D")
    games = pd.DataFrame(
        {
            "game_id": [f"g{i}" for i in range(6)],
            "game_date": dates,
            "home_team": ["AAA"] * 6,
            "away_team": ["BBB"] * 6,
            "home_runs": [1, 2, 3, 4, 5, 999],
            "away_runs": [0, 0, 0, 0, 0, 0],
            "margin_final": [1, 2, 3, 4, 5, 999],
            "season_start_year": [2024] * 6,
            "seasontype": ["rg"] * 6,
        }
    )
    table = games[["game_id", "season_start_year"]].copy()
    enriched = attach_runs_strength(table, games, window=30)

    first = enriched.loc[enriched["game_id"] == "g0", "home_rs_off"].iloc[0]
    last = enriched.loc[enriched["game_id"] == "g5", "home_rs_off"].iloc[0]

    assert first == pytest.approx(4.5)  # LEAGUE_RPG fill for no prior games
    assert last == pytest.approx(3.0)  # mean of prior home_runs 1..5 only
    assert last != pytest.approx(999.0)
    assert last < 100.0
