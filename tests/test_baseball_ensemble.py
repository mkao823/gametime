"""Unit tests for MLB pregame ensemble helpers (no network / MLB data)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from gametime.pregame.baseball.features import LEAGUE_FIP, LEAGUE_RPG
from gametime.pregame.baseball.ensemble import (
    _grid_search_target,
    combine,
    combine_equal,
    fit_weights,
    fit_weights_with_metrics,
    stack_fit,
    stack_fit_with_metrics,
    stack_predict,
)
from gametime.pregame.baseball.models.elo import attach_elo, fit_baseball_elo
from gametime.pregame.baseball.models.h2h import attach_h2h
from gametime.pregame.baseball.models.poisson import attach_poisson
from gametime.pregame.baseball.models.pythagorean import attach_pythagorean
from gametime.pregame.baseball.features import build_training_table
from gametime.pregame.baseball.models.park_factor import attach_park
from gametime.pregame.baseball.models.pitcher import attach_pitcher
from gametime.pregame.baseball.models.runs_strength import attach_runs_strength
from gametime.pregame.baseball.models.series_context import (
    SeriesContextMember,
    attach_series_context,
    latest_series_context_columns,
)
from gametime.pregame.baseball.models.travel_rest import (
    TravelRestMember, attach_travel_rest, latest_schedule_columns,
)
from gametime.pregame.baseball.models.weather import WeatherMember, attach_weather
from gametime.pregame.baseball.models.lineup import LineupMember, attach_lineup
from gametime.pregame.baseball.models.statcast_offense import (
    StatcastOffenseMember,
    attach_statcast_offense,
)
from gametime.ingest import mlb_statcast_offense
from gametime.ingest import mlb_weather
from gametime.ingest import mlb_lineup
from gametime.ingest.mlb_lineup import LEAGUE_WOBA
from gametime.ingest.mlb_statcast_offense import LEAGUE_XWOBA, STATCAST_OFFENSE_COLUMNS
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
    assert metrics["min_member_weight"] == 0.05


def test_grid_search_respects_min_member_weight_three_members():
    """Each active member must receive at least min_member_weight on the grid."""
    min_w = 0.05
    actual_total = np.array([9.0, 9.0, 9.0, 9.0])
    actual_margin = np.array([1.0, -1.0, 1.0, -1.0])
    members = [
        _member("a", [9.0, 9.0, 9.0, 9.0], [1.0, -1.0, 1.0, -1.0]),
        _member("b", [10.0, 8.0, 10.0, 8.0], [2.0, -2.0, 2.0, -2.0]),
        _member("c", [8.0, 10.0, 8.0, 10.0], [0.5, -0.5, 0.5, -0.5]),
    ]
    weights_total, weights_margin = fit_weights(
        members,
        actual_total,
        actual_margin,
        step=0.05,
        min_member_weight=min_w,
    )
    for name in ("a", "b", "c"):
        assert weights_total[name] >= min_w - 1e-9
        assert weights_margin[name] >= min_w - 1e-9
    assert sum(weights_total.values()) == pytest.approx(1.0, abs=1e-6)
    assert sum(weights_margin.values()) == pytest.approx(1.0, abs=1e-6)


def test_grid_search_tie_break_prefers_balanced_weights():
    """When MAE ties, prefer higher-entropy (more balanced) weights."""
    actual = np.array([5.0, 5.0, 5.0])
    stacks = {
        "a": np.array([5.0, 5.0, 5.0]),
        "b": np.array([5.0, 5.0, 5.0]),
        "c": np.array([5.0, 5.0, 5.0]),
    }
    names = ["a", "b", "c"]
    weights, mae = _grid_search_target(
        stacks, names, actual, step=0.05, min_member_weight=0.05
    )
    assert mae == pytest.approx(0.0)
    assert max(weights.values()) < 0.5
    assert min(weights.values()) >= 0.05 - 1e-9


def test_grid_search_respects_min_member_weight_four_members():
    """Four-member grid: each active member gets at least min_member_weight."""
    min_w = 0.05
    actual_total = np.array([9.0, 9.0, 9.0, 9.0])
    actual_margin = np.array([1.0, -1.0, 1.0, -1.0])
    members = [
        _member("a", [9.0, 9.0, 9.0, 9.0], [1.0, -1.0, 1.0, -1.0]),
        _member("b", [10.0, 8.0, 10.0, 8.0], [2.0, -2.0, 2.0, -2.0]),
        _member("c", [8.0, 10.0, 8.0, 10.0], [0.5, -0.5, 0.5, -0.5]),
        _member("d", [9.5, 8.5, 9.5, 8.5], [1.5, -1.5, 1.5, -1.5]),
    ]
    weights_total, weights_margin = fit_weights(
        members,
        actual_total,
        actual_margin,
        step=0.05,
        min_member_weight=min_w,
    )
    for name in ("a", "b", "c", "d"):
        assert weights_total[name] >= min_w - 1e-9
        assert weights_margin[name] >= min_w - 1e-9
    assert sum(weights_total.values()) == pytest.approx(1.0, abs=1e-6)
    assert sum(weights_margin.values()) == pytest.approx(1.0, abs=1e-6)


def test_grid_search_respects_min_member_weight_five_members():
    """Five-member grid: each active member gets at least min_member_weight."""
    min_w = 0.05
    actual_total = np.array([9.0, 9.0, 9.0, 9.0])
    actual_margin = np.array([1.0, -1.0, 1.0, -1.0])
    members = [
        _member("a", [9.0, 9.0, 9.0, 9.0], [1.0, -1.0, 1.0, -1.0]),
        _member("b", [10.0, 8.0, 10.0, 8.0], [2.0, -2.0, 2.0, -2.0]),
        _member("c", [8.0, 10.0, 8.0, 10.0], [0.5, -0.5, 0.5, -0.5]),
        _member("d", [9.5, 8.5, 9.5, 8.5], [1.5, -1.5, 1.5, -1.5]),
        _member("e", [9.2, 8.8, 9.2, 8.8], [1.2, -1.2, 1.2, -1.2]),
    ]
    weights_total, weights_margin = fit_weights(
        members,
        actual_total,
        actual_margin,
        step=0.05,
        min_member_weight=min_w,
    )
    for name in ("a", "b", "c", "d", "e"):
        assert weights_total[name] >= min_w - 1e-9
        assert weights_margin[name] >= min_w - 1e-9
    assert sum(weights_total.values()) == pytest.approx(1.0, abs=1e-6)
    assert sum(weights_margin.values()) == pytest.approx(1.0, abs=1e-6)


def test_grid_search_respects_min_member_weight_six_members():
    """Six-member grid: each active member gets at least min_member_weight."""
    min_w = 0.05
    actual_total = np.array([9.0, 9.0, 9.0, 9.0])
    actual_margin = np.array([1.0, -1.0, 1.0, -1.0])
    members = [
        _member("a", [9.0, 9.0, 9.0, 9.0], [1.0, -1.0, 1.0, -1.0]),
        _member("b", [10.0, 8.0, 10.0, 8.0], [2.0, -2.0, 2.0, -2.0]),
        _member("c", [8.0, 10.0, 8.0, 10.0], [0.5, -0.5, 0.5, -0.5]),
        _member("d", [9.5, 8.5, 9.5, 8.5], [1.5, -1.5, 1.5, -1.5]),
        _member("e", [9.2, 8.8, 9.2, 8.8], [1.2, -1.2, 1.2, -1.2]),
        _member("f", [9.1, 8.9, 9.1, 8.9], [0.8, -0.8, 0.8, -0.8]),
    ]
    weights_total, weights_margin = fit_weights(
        members,
        actual_total,
        actual_margin,
        step=0.05,
        min_member_weight=min_w,
    )
    for name in ("a", "b", "c", "d", "e", "f"):
        assert weights_total[name] >= min_w - 1e-9
        assert weights_margin[name] >= min_w - 1e-9
    assert sum(weights_total.values()) == pytest.approx(1.0, abs=1e-6)
    assert sum(weights_margin.values()) == pytest.approx(1.0, abs=1e-6)


def test_stack_fit_predict_recovers_known_linear_combo():
    """Ridge should recover a fixed linear blend on synthetic member preds."""
    n = 40
    rng = np.random.default_rng(0)
    actual_total = rng.uniform(7.0, 11.0, size=n)
    actual_margin = rng.uniform(-3.0, 3.0, size=n)
    members = [
        _member("a", (actual_total + 0.3).tolist(), (actual_margin - 0.2).tolist()),
        _member("b", (actual_total - 0.1).tolist(), (actual_margin + 0.4).tolist()),
        _member("c", (actual_total + 0.05).tolist(), (actual_margin + 0.1).tolist()),
    ]
    stacker = stack_fit(members, actual_total, actual_margin, alpha=0.01)
    stacked = stack_predict(members, stacker)
    linear = combine(
        members,
        weights_total={"a": 0.5, "b": 0.3, "c": 0.2},
        weights_margin={"a": 0.4, "b": 0.4, "c": 0.2},
    )
    stack_mae_total = float(np.mean(np.abs(stacked.total - actual_total)))
    linear_mae_total = float(np.mean(np.abs(linear.total - actual_total)))
    assert stack_mae_total <= linear_mae_total + 0.05


def test_stack_fit_with_metrics_keys():
    actual_total = np.array([8.0, 10.0, 9.0, 11.0])
    actual_margin = np.array([2.0, -1.0, 0.5, 1.0])
    members = [
        _member("m1", [8.5, 9.5, 9.0, 10.5], [2.0, -0.5, 0.0, 0.8]),
        _member("m2", [7.5, 10.5, 9.5, 11.5], [1.5, -1.5, 1.0, 1.2]),
    ]
    stacker, metrics = stack_fit_with_metrics(
        members, actual_total, actual_margin, alpha=1.0
    )
    assert "total" in stacker and "margin" in stacker
    for target in ("total", "margin"):
        assert set(stacker[target]) >= {"members", "intercept", "coef", "alpha"}
    assert set(metrics) >= {"n", "total_mae", "margin_mae", "winner_accuracy", "alpha"}
    out = stack_predict(members, stacker)
    assert len(out.total) == len(actual_total)
    assert len(out.margin) == len(actual_margin)


def test_stack_predict_rejects_member_order_mismatch():
    actual_total = np.array([9.0, 9.0])
    actual_margin = np.array([1.0, -1.0])
    fit_members = [
        _member("a", [9.0, 9.0], [1.0, -1.0]),
        _member("b", [9.5, 8.5], [1.5, -1.5]),
    ]
    stacker = stack_fit(fit_members, actual_total, actual_margin)
    predict_members = [
        _member("b", [9.5, 8.5], [1.5, -1.5]),
        _member("a", [9.0, 9.0], [1.0, -1.0]),
    ]
    with pytest.raises(ValueError, match="member order"):
        stack_predict(predict_members, stacker)


def test_attach_elo_excludes_current_game_runs():
    """Pre-game Elo for game g must use only prior game results."""
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
    enriched = attach_elo(table, games)

    games_prior = games.iloc[:5].copy()
    _, win_prior, off_prior = fit_baseball_elo(games_prior)
    last_home_elo = enriched.loc[enriched["game_id"] == "g5", "home_elo_pre"].iloc[0]
    last_home_off = enriched.loc[enriched["game_id"] == "g5", "home_off_elo_pre"].iloc[0]

    assert last_home_elo == pytest.approx(win_prior.rating("AAA"))
    assert last_home_off == pytest.approx(off_prior.off_rating("AAA"))
    assert last_home_elo != pytest.approx(999.0)


def test_attach_poisson_excludes_current_game_runs():
    """Poisson rates for game g must use only prior games (shifted expanding mean)."""
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
    enriched = attach_poisson(table, games)

    first = enriched.loc[enriched["game_id"] == "g0", "home_poisson_attack"].iloc[0]
    last = enriched.loc[enriched["game_id"] == "g5", "home_poisson_attack"].iloc[0]

    assert first == pytest.approx(4.5)  # LEAGUE_RPG fill for no prior games
    assert last == pytest.approx(3.0)  # mean of prior home_runs 1..5 only
    assert last != pytest.approx(999.0)
    assert last < 100.0


def test_attach_pythagorean_excludes_current_game_runs():
    """Pythagorean RS for game g must use only prior games in the season (shifted)."""
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
    enriched = attach_pythagorean(table, games)

    first = enriched.loc[enriched["game_id"] == "g0", "home_pyth_rs"].iloc[0]
    last = enriched.loc[enriched["game_id"] == "g5", "home_pyth_rs"].iloc[0]

    assert first == pytest.approx(LEAGUE_RPG)
    assert last == pytest.approx(15.0)  # sum of prior home_runs 1..5 only
    assert last != pytest.approx(999.0)
    assert last < 100.0


def test_grid_search_respects_min_member_weight_eight_members():
    """Eight-member grid: each active member gets at least min_member_weight."""
    min_w = 0.05
    actual_total = np.array([9.0, 9.0, 9.0, 9.0])
    actual_margin = np.array([1.0, -1.0, 1.0, -1.0])
    members = [
        _member("a", [9.0, 9.0, 9.0, 9.0], [1.0, -1.0, 1.0, -1.0]),
        _member("b", [10.0, 8.0, 10.0, 8.0], [2.0, -2.0, 2.0, -2.0]),
        _member("c", [8.0, 10.0, 8.0, 10.0], [0.5, -0.5, 0.5, -0.5]),
        _member("d", [9.5, 8.5, 9.5, 8.5], [1.5, -1.5, 1.5, -1.5]),
        _member("e", [9.2, 8.8, 9.2, 8.8], [1.2, -1.2, 1.2, -1.2]),
        _member("f", [9.1, 8.9, 9.1, 8.9], [0.8, -0.8, 0.8, -0.8]),
        _member("g", [9.3, 8.7, 9.3, 8.7], [1.1, -1.1, 1.1, -1.1]),
        _member("h", [9.4, 8.6, 9.4, 8.6], [0.9, -0.9, 0.9, -0.9]),
    ]
    weights_total, weights_margin = fit_weights(
        members,
        actual_total,
        actual_margin,
        step=0.05,
        min_member_weight=min_w,
    )
    for name in ("a", "b", "c", "d", "e", "f", "g", "h"):
        assert weights_total[name] >= min_w - 1e-9
        assert weights_margin[name] >= min_w - 1e-9
    assert sum(weights_total.values()) == pytest.approx(1.0, abs=1e-6)
    assert sum(weights_margin.values()) == pytest.approx(1.0, abs=1e-6)


def test_grid_search_respects_max_member_weight():
    """Dominant member is capped; uncapped search can exceed the cap."""
    actual = np.array([9.0, 9.0, 9.0, 9.0])
    stacks = {
        "a": np.array([9.0, 9.0, 9.0, 9.0]),
        "b": np.array([12.0, 6.0, 12.0, 6.0]),
        "c": np.array([20.0, 20.0, 20.0, 20.0]),
    }
    names = ["a", "b", "c"]
    cap = 0.45
    uncapped, _ = _grid_search_target(
        stacks, names, actual, step=0.1, min_member_weight=0.05
    )
    capped, _ = _grid_search_target(
        stacks,
        names,
        actual,
        step=0.1,
        min_member_weight=0.05,
        max_member_weight=cap,
    )
    assert max(uncapped.values()) > cap + 1e-9
    assert max(capped.values()) <= cap + 1e-9
    assert sum(capped.values()) == pytest.approx(1.0, abs=1e-6)


def test_fit_weights_respects_max_member_weight_per_target():
    """Total and margin caps are enforced independently."""
    cap = 0.45
    actual_total = np.array([9.0, 9.0, 9.0, 9.0])
    actual_margin = np.array([1.0, -1.0, 1.0, -1.0])
    members = [
        _member("a", [9.0, 9.0, 9.0, 9.0], [1.0, -1.0, 1.0, -1.0]),
        _member("b", [12.0, 6.0, 12.0, 6.0], [2.0, -2.0, 2.0, -2.0]),
        _member("c", [6.0, 12.0, 6.0, 12.0], [0.5, -0.5, 0.5, -0.5]),
    ]
    weights_total, weights_margin = fit_weights(
        members,
        actual_total,
        actual_margin,
        step=0.05,
        min_member_weight=0.05,
        max_member_weight=cap,
    )
    assert max(weights_total.values()) <= cap + 1e-9
    assert max(weights_margin.values()) <= cap + 1e-9


def test_fit_weights_with_metrics_records_max_member_weight():
    members = [
        _member("m1", [8.5, 9.5, 9.0], [2.0, -0.5, 0.0]),
        _member("m2", [7.5, 10.5, 9.5], [1.5, -1.5, 1.0]),
    ]
    _, _, metrics = fit_weights_with_metrics(
        members,
        np.array([9.0, 9.0, 9.0]),
        np.array([1.0, -1.0, 1.0]),
        step=0.1,
        max_member_weight=0.45,
    )
    assert metrics["max_member_weight"] == 0.45




def test_attach_pitcher_missing_sidecar_uses_league_fallback():
    dates = pd.date_range("2024-04-01", periods=3, freq="D")
    games = pd.DataFrame(
        {
            "game_id": [f"g{i}" for i in range(3)],
            "game_date": dates,
            "home_team": ["AAA"] * 3,
            "away_team": ["BBB"] * 3,
            "home_runs": [4, 5, 6],
            "away_runs": [3, 2, 1],
            "margin_final": [1, 3, 5],
            "season_start_year": [2024] * 3,
            "seasontype": ["rg"] * 3,
        }
    )
    table = build_training_table(games)
    enriched = attach_pitcher(table, pd.DataFrame())
    assert (enriched["has_starting_pitcher"] == 0).all()
    assert enriched.loc[0, "home_sp_fip"] == pytest.approx(LEAGUE_FIP)
    assert enriched.loc[0, "sp_fip_diff"] == pytest.approx(0.0)


def test_attach_pitcher_prior_fip_not_from_current_game_line():
    """Sidecar FIP for g1 must match pre-stored prior, not post-game disaster."""
    dates = pd.date_range("2024-04-01", periods=2, freq="D")
    games = pd.DataFrame(
        {
            "game_id": ["g0", "g1"],
            "game_date": dates,
            "home_team": ["AAA", "AAA"],
            "away_team": ["BBB", "BBB"],
            "home_runs": [3, 3],
            "away_runs": [2, 2],
            "margin_final": [1, 1],
            "season_start_year": [2024, 2024],
            "seasontype": ["rg", "rg"],
        }
    )
    pitcher_games = pd.DataFrame(
        {
            "game_id": ["g0", "g1"],
            "home_sp_id": [100, 100],
            "away_sp_id": [200, 200],
            "home_sp_fip": [4.2, 3.8],
            "away_sp_fip": [4.0, 4.0],
            "home_sp_rest_days": [5.0, 4.0],
            "away_sp_rest_days": [5.0, 5.0],
            "has_starting_pitcher": [1, 1],
        }
    )
    table = build_training_table(games)
    enriched = attach_pitcher(table, pitcher_games)
    g1_home_fip = enriched.loc[enriched["game_id"] == "g1", "home_sp_fip"].iloc[0]
    assert g1_home_fip == pytest.approx(3.8)
    assert g1_home_fip != pytest.approx(9.99)




def test_attach_park_excludes_current_game_total():
    dates = pd.date_range("2024-04-01", periods=6, freq="D")
    games = pd.DataFrame(
        {
            "game_id": [f"g{i}" for i in range(6)],
            "game_date": dates,
            "home_team": ["COL"] * 6,
            "away_team": ["AAA"] * 6,
            "home_runs": [5, 5, 5, 5, 5, 25],
            "away_runs": [4, 4, 4, 4, 4, 25],
            "margin_final": [1, 1, 1, 1, 1, 0],
            "total_final": [9, 9, 9, 9, 9, 50],
            "season_start_year": [2024] * 6,
            "seasontype": ["rg"] * 6,
        }
    )
    table = games[["game_id", "home_team", "season_start_year"]].copy()
    enriched = attach_park(table, games, pd.DataFrame())
    g5_pf = enriched.loc[enriched["game_id"] == "g5", "home_park_factor"].iloc[0]
    assert g5_pf == pytest.approx(1.0)
    assert g5_pf != pytest.approx(50 / 9.0)


def test_attach_park_static_fallback_for_inference():
    games = pd.DataFrame(
        {
            "game_id": ["g0"],
            "game_date": pd.to_datetime(["2024-04-01"]),
            "home_team": ["COL"],
            "away_team": ["AAA"],
            "home_runs": [5],
            "away_runs": [4],
            "margin_final": [1],
            "total_final": [9],
            "season_start_year": [2024],
            "seasontype": ["rg"],
        }
    )
    static = pd.DataFrame(
        {"home_team": ["COL"], "park_factor_runs": [1.15], "park_factor_hr": [np.nan]}
    )
    table = games[["game_id", "home_team", "season_start_year"]].copy()
    enriched = attach_park(table, games, static)
    assert enriched.loc[0, "home_park_factor"] == pytest.approx(1.15)
    assert enriched.loc[0, "has_park_factor"] == 1


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


def test_attach_h2h_excludes_current_and_future_meetings():
    dates = pd.date_range("2024-04-01", periods=4, freq="D")
    games = pd.DataFrame(
        {
            "game_id": ["g0", "g1", "g2", "g3"],
            "game_date": dates,
            "home_team": ["AAA", "BBB", "AAA", "AAA"],
            "away_team": ["BBB", "AAA", "BBB", "BBB"],
            "home_runs": [5, 1, 999, 2],
            "away_runs": [3, 9, 0, 1],
            "margin_final": [2, -8, 999, 1],
            "season_start_year": [2024] * 4,
            "seasontype": ["rg"] * 4,
        }
    )
    enriched = attach_h2h(
        games[["game_id", "season_start_year"]], games, window=10, shrink_k=8.0
    )
    assert enriched.loc[enriched["game_id"] == "g0", "h2h_n_meetings"].iloc[0] == 0
    assert enriched.loc[enriched["game_id"] == "g2", "h2h_n_meetings"].iloc[0] == 2
    assert enriched.loc[enriched["game_id"] == "g2", "h2h_raw_margin"].iloc[0] == pytest.approx(
        -3.0
    )


def test_attach_travel_rest_no_leakage_games_last_3d():
    dates = pd.date_range("2024-04-01", periods=6, freq="D")
    games = pd.DataFrame({"game_id": [f"g{i}" for i in range(6)], "game_date": dates,
        "home_team": ["AAA"]*6, "away_team": ["BBB"]*6, "home_runs": [3]*6, "away_runs": [2]*6,
        "margin_final": [1]*6, "season_start_year": [2024]*6, "seasontype": ["rg"]*6})
    enriched = attach_travel_rest(build_training_table(games), games)
    assert enriched.loc[enriched["game_id"]=="g0","home_games_last_3d"].iloc[0]==0.0
    assert enriched.loc[enriched["game_id"]=="g5","home_games_last_3d"].iloc[0]==pytest.approx(3.0)


def test_attach_travel_rest_doubleheader_flag():
    games = pd.DataFrame({"game_id":["dh1","dh2","solo"],
        "game_date":pd.to_datetime(["2024-04-01","2024-04-01","2024-04-02"]),
        "home_team":["AAA","AAA","AAA"], "away_team":["BBB","CCC","BBB"],
        "home_runs":[4,5,3], "away_runs":[3,2,2], "margin_final":[1,3,1],
        "season_start_year":[2024,2024,2024], "seasontype":["rg","rg","rg"]})
    enriched = attach_travel_rest(build_training_table(games), games)
    assert enriched.loc[enriched["game_id"]=="dh1","is_doubleheader"].iloc[0]==1


def test_attach_travel_rest_sparse_schedule_fallback():
    games = pd.DataFrame({"game_id":["only"], "game_date":[pd.Timestamp("2024-04-01")],
        "home_team":["AAA"], "away_team":["BBB"], "home_runs":[4], "away_runs":[3],
        "margin_final":[1], "season_start_year":[2024], "seasontype":["rg"]})
    row = attach_travel_rest(build_training_table(games), games).iloc[0]
    assert row["home_games_last_3d"]==0.0 and row["schedule_fatigue_diff"]==pytest.approx(0.0)


def test_travel_rest_member_predicts():
    dates = pd.date_range("2024-04-01", periods=8, freq="D")
    games = pd.DataFrame({"game_id":[f"g{i}" for i in range(8)], "game_date":dates,
        "home_team":["H1"]*4+["A1"]*4, "away_team":["A1"]*4+["H1"]*4,
        "home_runs":[4,5,3,6,2,4,5,3], "away_runs":[3,2,4,1,5,3,2,4],
        "margin_final":[1,3,-1,5,-3,1,3,-1], "total_final":[7.0]*8,
        "season_start_year":[2024]*8, "seasontype":["rg"]*8})
    enriched = attach_travel_rest(build_training_table(games), games)
    member = TravelRestMember(); member.fit(enriched.iloc[:4])
    pred = member.predict(enriched.iloc[4:5])
    assert np.isfinite(pred.total[0]) and np.isfinite(pred.margin[0])


def test_latest_schedule_columns_empty_games():
    cols = latest_schedule_columns(home="SEA", away="CHW", games=pd.DataFrame())
    assert cols["home_games_last_3d"] == 0.0


def test_attach_weather_by_game_id_and_dome_handling():
    games = pd.DataFrame(
        {
            "game_id": ["g0", "g1"],
            "game_date": pd.to_datetime(["2024-04-01", "2024-04-02"]),
            "home_team": ["SEA", "LAD"],
            "away_team": ["BOS", "NYY"],
            "home_runs": [4, 5],
            "away_runs": [3, 4],
            "total_final": [7, 9],
            "margin_final": [1, 1],
            "season_start_year": [2024, 2024],
            "seasontype": ["rg", "rg"],
        }
    )
    table = build_training_table(games)
    weather_games = pd.DataFrame(
        {
            "game_id": ["g0", "g1"],
            "home_team": ["SEA", "LAD"],
            "game_date": pd.to_datetime(["2024-04-01", "2024-04-02"]),
            "temp_f": [65.0, 72.0],
            "wind_mph": [9.0, 8.0],
            "humidity_pct": [71.0, 52.0],
            "is_dome": [1, 0],
            "has_weather": [1, 1],
        }
    )
    enriched = attach_weather(table, weather_games)
    assert enriched.loc[enriched["game_id"] == "g0", "wind_mph"].iloc[0] == pytest.approx(0.0)
    assert enriched.loc[enriched["game_id"] == "g1", "wind_mph"].iloc[0] == pytest.approx(8.0)
    assert (enriched["has_weather"] == 1).all()


def test_attach_weather_fallback_when_sidecar_missing():
    games = pd.DataFrame(
        {
            "game_id": ["g0"],
            "game_date": pd.to_datetime(["2024-04-01"]),
            "home_team": ["AAA"],
            "away_team": ["BBB"],
            "home_runs": [4],
            "away_runs": [3],
            "total_final": [7],
            "margin_final": [1],
            "season_start_year": [2024],
            "seasontype": ["rg"],
        }
    )
    table = build_training_table(games)
    enriched = attach_weather(table, pd.DataFrame())
    row = enriched.iloc[0]
    assert row["has_weather"] == 0
    assert row["temp_f"] == pytest.approx(70.0)
    assert row["wind_mph"] == pytest.approx(0.0)


def test_weather_member_predicts_with_deterministic_fallback():
    df = pd.DataFrame(
        {
            "temp_f": [65.0, 70.0, 80.0],
            "wind_mph": [8.0, 0.0, 12.0],
            "humidity_pct": [65.0, 50.0, 45.0],
            "is_dome": [0, 1, 0],
            "has_weather": [1, 0, 1],
            "total_final": [8.5, 8.7, 9.1],
            "margin_final": [0.1, 0.0, 0.2],
        }
    )
    member = WeatherMember()
    member.fit(df.iloc[:2])
    pred = member.predict(df.iloc[1:2])
    assert np.isfinite(pred.total[0])
    assert np.isfinite(pred.margin[0])


def test_weather_ingest_row_alignment_uses_game_id_keys(tmp_path):
    games = pd.DataFrame(
        {
            "game_id": ["g0", "g1"],
            "game_date": pd.to_datetime(["2024-04-01", "2024-04-02"]),
            "home_team": ["SEA", "LAD"],
            "away_team": ["BOS", "NYY"],
        }
    )
    orig = mlb_weather._fetch_daily_weather
    try:
        mlb_weather._fetch_daily_weather = lambda **_: {
            "temp_f": 68.0,
            "wind_mph": 7.0,
            "humidity_pct": 60.0,
            "is_dome": 0,
        }
        weather = mlb_weather.build_weather_games_table(
            games,
            cache_dir=tmp_path / "weather_cache",
            pause=0.0,
        )
    finally:
        mlb_weather._fetch_daily_weather = orig
    assert set(weather["game_id"].astype(str)) == {"g0", "g1"}
    assert set(weather["home_team"].astype(str)) == {"SEA", "LAD"}


def test_attach_series_context_no_leakage_prior_game():
    """Game N series features must not use game N's own linescore."""
    dates = pd.date_range("2024-04-01", periods=4, freq="D")
    games = pd.DataFrame(
        {
            "game_id": ["g0", "g1", "g2", "g3"],
            "game_date": dates,
            "home_team": ["AAA"] * 4,
            "away_team": ["BBB"] * 4,
            "home_runs": [5, 1, 999, 2],
            "away_runs": [3, 9, 0, 1],
            "margin_final": [2, -8, 999, 1],
            "total_final": [8.0, 10.0, 999.0, 3.0],
            "season_start_year": [2024] * 4,
            "seasontype": ["rg"] * 4,
        }
    )
    enriched = attach_series_context(
        games[["game_id", "season_start_year"]], games
    )
    g0 = enriched.loc[enriched["game_id"] == "g0"].iloc[0]
    g2 = enriched.loc[enriched["game_id"] == "g2"].iloc[0]
    assert g0["series_game_num"] == 1.0
    assert g0["prior_game_total"] == pytest.approx(2.0 * LEAGUE_RPG)
    assert g2["series_game_num"] == 3.0
    assert g2["prior_game_margin"] == pytest.approx(-8.0)
    assert g2["prior_game_total"] == pytest.approx(10.0)
    assert g2["prior_game_margin"] != pytest.approx(999.0)


def test_attach_series_context_series_break_resets_game_num():
    dates = pd.to_datetime(["2024-04-01", "2024-04-02", "2024-04-05"])
    games = pd.DataFrame(
        {
            "game_id": ["g0", "g1", "g2"],
            "game_date": dates,
            "home_team": ["AAA", "AAA", "AAA"],
            "away_team": ["BBB", "BBB", "BBB"],
            "home_runs": [4, 5, 3],
            "away_runs": [3, 2, 4],
            "margin_final": [1, 3, -1],
            "total_final": [7.0, 7.0, 7.0],
            "season_start_year": [2024] * 3,
            "seasontype": ["rg"] * 3,
        }
    )
    enriched = attach_series_context(games[["game_id"]], games)
    assert enriched.loc[enriched["game_id"] == "g2", "series_game_num"].iloc[0] == 1.0


def test_series_context_member_predicts():
    dates = pd.date_range("2024-04-01", periods=6, freq="D")
    games = pd.DataFrame(
        {
            "game_id": [f"g{i}" for i in range(6)],
            "game_date": dates,
            "home_team": ["AAA"] * 6,
            "away_team": ["BBB"] * 6,
            "home_runs": [4, 5, 3, 6, 2, 4],
            "away_runs": [3, 2, 4, 1, 5, 3],
            "margin_final": [1, 3, -1, 5, -3, 1],
            "total_final": [7.0] * 6,
            "season_start_year": [2024] * 6,
            "seasontype": ["rg"] * 6,
        }
    )
    enriched = attach_series_context(build_training_table(games), games)
    member = SeriesContextMember()
    member.fit(enriched.iloc[:3])
    pred = member.predict(enriched.iloc[3:4])
    assert np.isfinite(pred.total[0]) and np.isfinite(pred.margin[0])


def test_latest_series_context_columns_empty_games():
    cols = latest_series_context_columns(pd.DataFrame(), home="NYY", away="BOS")
    assert cols["series_game_num"] == 1.0
    assert cols["has_series_context"] == 0.0


def test_ensemble_thirteen_member_count_from_config():
    from pathlib import Path

    import yaml

    cfg = yaml.safe_load((Path("configs/mlb.yaml")).read_text())
    members = cfg["pregame"]["ensemble"]["members"]
    assert "lineup" in members
    assert "series_context" in members
    assert len(members) == 13


def test_grid_search_respects_min_member_weight_thirteen_members():
    min_w = 0.05
    actual_total = np.array([9.0, 9.0, 9.0, 9.0])
    actual_margin = np.array([1.0, -1.0, 1.0, -1.0])
    members = [
        _member(f"m{i}", [9.0, 9.0, 9.0, 9.0], [1.0, -1.0, 1.0, -1.0])
        for i in range(13)
    ]
    weights_total, weights_margin = fit_weights(
        members,
        actual_total,
        actual_margin,
        step=0.05,
        min_member_weight=min_w,
    )
    for i in range(13):
        name = f"m{i}"
        assert weights_total[name] >= min_w - 1e-9
        assert weights_margin[name] >= min_w - 1e-9


def test_attach_lineup_by_game_id():
    games = pd.DataFrame(
        {
            "game_id": ["g0", "g1"],
            "game_date": pd.to_datetime(["2024-04-01", "2024-04-02"]),
            "home_team": ["NYY", "BOS"],
            "away_team": ["BOS", "NYY"],
            "home_runs": [5, 4],
            "away_runs": [3, 5],
            "total_final": [8, 9],
            "margin_final": [2, -1],
            "season_start_year": [2024, 2024],
            "seasontype": ["rg", "rg"],
        }
    )
    table = build_training_table(games)
    lineup_games = pd.DataFrame(
        {
            "game_id": ["g0", "g1"],
            "home_lineup_woba": [0.340, 0.325],
            "away_lineup_woba": [0.310, 0.335],
            "lineup_platoon_diff": [0.030, -0.010],
            "has_lineup": [1, 1],
        }
    )
    enriched = attach_lineup(table, lineup_games)
    assert enriched.loc[enriched["game_id"] == "g0", "home_lineup_woba"].iloc[0] == pytest.approx(
        0.340
    )
    assert (enriched["has_lineup"] == 1).all()


def test_attach_lineup_fallback_when_sidecar_missing():
    games = pd.DataFrame(
        {
            "game_id": ["g0"],
            "game_date": pd.to_datetime(["2024-04-01"]),
            "home_team": ["AAA"],
            "away_team": ["BBB"],
            "home_runs": [4],
            "away_runs": [3],
            "total_final": [7],
            "margin_final": [1],
            "season_start_year": [2024],
            "seasontype": ["rg"],
        }
    )
    table = build_training_table(games)
    enriched = attach_lineup(table, pd.DataFrame())
    row = enriched.iloc[0]
    assert row["has_lineup"] == 0
    assert row["home_lineup_woba"] == pytest.approx(LEAGUE_WOBA)
    assert row["lineup_platoon_diff"] == pytest.approx(0.0)


def test_lineup_member_predicts_with_fallback():
    df = pd.DataFrame(
        {
            "home_lineup_woba": [0.340, LEAGUE_WOBA],
            "away_lineup_woba": [0.310, LEAGUE_WOBA],
            "lineup_platoon_diff": [0.030, 0.0],
            "has_lineup": [1, 0],
            "total_final": [8.5, 8.7],
            "margin_final": [0.1, 0.0],
        }
    )
    member = LineupMember()
    member.fit(df.iloc[:1])
    pred = member.predict(df.iloc[1:2])
    assert np.isfinite(pred.total[0])
    assert np.isfinite(pred.margin[0])


def test_lineup_ingest_row_alignment_uses_game_id_keys(tmp_path):
    dates = pd.date_range("2024-04-01", periods=8, freq="D")
    games = pd.DataFrame(
        {
            "game_id": [f"g{i}" for i in range(8)],
            "game_date": dates,
            "home_team": ["NYY", "BOS"] * 4,
            "away_team": ["BOS", "NYY"] * 4,
            "home_runs": [5, 4, 6, 3, 5, 4, 7, 2],
            "away_runs": [3, 5, 2, 4, 3, 5, 1, 6],
            "season_start_year": [2024] * 8,
        }
    )
    lineup = mlb_lineup.build_lineup_games_table(
        games,
        min_season=2099,
        cache_dir=tmp_path / "lineup_cache",
    )
    assert set(lineup["game_id"].astype(str)) == {f"g{i}" for i in range(8)}
    assert lineup["home_lineup_woba"].nunique() > 1


def test_aggregate_day_statcast_team_batting():
    raw = pd.DataFrame(
        {
            "game_date": ["2024-06-01"] * 4,
            "home_team": ["NYY"] * 4,
            "away_team": ["BOS"] * 4,
            "inning_topbot": ["Top", "Top", "Bot", "Bot"],
            "woba_value": [0.5, 0.0, 0.8, 0.0],
            "woba_denom": [1, 1, 1, 0],
            "launch_speed": [98.0, np.nan, 88.0, np.nan],
            "launch_speed_angle": [6, np.nan, 3, np.nan],
        }
    )
    agg = mlb_statcast_offense._aggregate_day_statcast(raw)
    bos = agg.loc[agg["team"] == "BOS"].iloc[0]
    nyy = agg.loc[agg["team"] == "NYY"].iloc[0]
    assert bos["pa"] == 2
    assert bos["barrels"] == 1
    assert bos["hard_hits"] == 1
    assert nyy["pa"] == 1
    assert nyy["bbe"] == 1
    assert nyy["barrels"] == 0


def test_team_rolling_metrics_shift_one_no_same_day_leakage():
    daily = pd.DataFrame(
        {
            "team": ["AAA"] * 5,
            "game_date": pd.date_range("2024-06-01", periods=5),
            "pa": [10, 10, 10, 10, 10],
            "xwoba_num": [3.0, 3.2, 3.4, 3.6, 3.8],
            "xwoba_den": [10, 10, 10, 10, 10],
            "bbe": [6, 6, 6, 6, 6],
            "barrels": [1, 1, 1, 1, 1],
            "hard_hits": [3, 3, 3, 3, 3],
        }
    )
    roll = mlb_statcast_offense._team_rolling_metrics(daily, window=3, min_pa=20)
    first = roll.iloc[0]
    assert first["has_statcast"] == 0
    assert first["xwoba_roll"] == pytest.approx(LEAGUE_XWOBA)
    later = roll.iloc[4]
    assert later["has_statcast"] == 1
    assert later["xwoba_roll"] == pytest.approx(0.34)


def test_attach_statcast_offense_by_game_id():
    games = pd.DataFrame(
        {
            "game_id": ["g0", "g1"],
            "game_date": pd.to_datetime(["2024-06-10", "2024-06-11"]),
            "home_team": ["NYY", "BOS"],
            "away_team": ["BOS", "NYY"],
            "home_runs": [5, 4],
            "away_runs": [3, 5],
            "total_final": [8, 9],
            "margin_final": [2, -1],
            "season_start_year": [2024, 2024],
            "seasontype": ["rg", "rg"],
        }
    )
    table = build_training_table(games)
    sidecar = pd.DataFrame(
        {
            "game_id": ["g0", "g1"],
            "home_xwoba_roll": [0.340, 0.325],
            "away_xwoba_roll": [0.310, 0.335],
            "home_barrel_pct_roll": [0.090, 0.085],
            "away_barrel_pct_roll": [0.075, 0.080],
            "home_hard_hit_pct_roll": [0.410, 0.400],
            "away_hard_hit_pct_roll": [0.380, 0.390],
            "xwoba_off_diff": [0.030, -0.010],
            "has_statcast_offense": [1, 1],
        }
    )
    enriched = attach_statcast_offense(table, sidecar)
    assert enriched.loc[enriched["game_id"] == "g0", "home_xwoba_roll"].iloc[0] == pytest.approx(0.340)
    assert (enriched["has_statcast_offense"] == 1).all()


def test_attach_statcast_offense_fallback_when_sidecar_missing():
    games = pd.DataFrame(
        {
            "game_id": ["g0"],
            "game_date": pd.to_datetime(["2024-06-10"]),
            "home_team": ["AAA"],
            "away_team": ["BBB"],
            "home_runs": [4],
            "away_runs": [3],
            "total_final": [7],
            "margin_final": [1],
            "season_start_year": [2024],
            "seasontype": ["rg"],
        }
    )
    table = build_training_table(games)
    enriched = attach_statcast_offense(table, pd.DataFrame())
    row = enriched.iloc[0]
    assert row["has_statcast_offense"] == 0
    assert row["home_xwoba_roll"] == pytest.approx(LEAGUE_XWOBA)
    assert row["xwoba_off_diff"] == pytest.approx(0.0)


def test_statcast_offense_member_predicts_with_fallback():
    df = pd.DataFrame(
        {
            "home_xwoba_roll": [0.340, LEAGUE_XWOBA],
            "away_xwoba_roll": [0.310, LEAGUE_XWOBA],
            "home_barrel_pct_roll": [0.090, 0.080],
            "away_barrel_pct_roll": [0.075, 0.080],
            "has_statcast_offense": [1, 0],
            "total_final": [8.5, 8.7],
            "margin_final": [0.1, 0.0],
        }
    )
    member = StatcastOffenseMember()
    member.fit(df.iloc[:1])
    pred = member.predict(df.iloc[1:2])
    assert np.isfinite(pred.total[0])
    assert np.isfinite(pred.margin[0])


def test_statcast_offense_sidecar_columns_constant():
    assert "has_statcast_offense" in STATCAST_OFFENSE_COLUMNS
    assert "xwoba_off_diff" in STATCAST_OFFENSE_COLUMNS
