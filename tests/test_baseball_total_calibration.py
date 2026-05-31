"""Tests for MLB post-ensemble total calibration (W9)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from gametime.pregame.calibration import (
    TotalCalibration,
    fit_total_calibration,
    load_total_calibration,
    save_total_calibration,
    total_band_bias,
    total_calibration_metrics,
)


def test_affine_total_calibration_round_trip():
    pred = np.linspace(6.0, 12.0, 50)
    actual = 1.4 * pred - 2.0
    cal = fit_total_calibration(pred, actual, val_season=2024)
    assert cal.type == "affine"
    assert cal.slope == pytest.approx(1.4, abs=0.05)
    assert cal.intercept == pytest.approx(-2.0, abs=0.05)
    np.testing.assert_allclose(cal.apply(pred), actual, rtol=0.05, atol=0.15)


def test_isotonic_total_calibration_monotonic():
    rng = np.random.default_rng(42)
    pred = np.sort(rng.uniform(6.0, 12.0, 80))
    actual = np.clip(0.5 * pred**1.1 + 2.0, 3.0, 20.0)
    cal = fit_total_calibration(pred, actual, val_season=2024)
    assert cal.type in {"affine", "isotonic"}
    grid = np.linspace(float(np.min(pred)), float(np.max(pred)), 30)
    mapped = cal.apply(grid)
    assert np.all(np.diff(mapped) >= -1e-9)


def test_total_calibration_save_load(tmp_path: Path):
    cal = TotalCalibration(
        type="affine",
        slope=1.2,
        intercept=-0.3,
        fit_split="val",
        val_season=2024,
        n_fit=100,
    )
    path = tmp_path / "total_calibration.json"
    save_total_calibration(cal, path)
    loaded = load_total_calibration(path)
    assert loaded.slope == cal.slope
    assert loaded.intercept == cal.intercept
    assert loaded.val_season == 2024
    assert json.loads(path.read_text())["type"] == "affine"


def test_fit_total_calibration_small_sample_identity():
    pred = np.array([8.0, 9.0, 9.5])
    actual = np.array([7.0, 10.0, 9.0])
    cal = fit_total_calibration(pred, actual)
    assert cal.n_fit == 3
    np.testing.assert_allclose(cal.apply(pred), pred)


def test_total_band_bias_signs():
    pred = np.array([9.0, 9.0, 9.0, 9.0, 9.0, 9.0])
    actual = np.array([5.0, 6.0, 8.0, 10.0, 12.0, 14.0])
    bands = total_band_bias(pred, actual)
    assert bands["lt_7"] == pytest.approx(3.5)
    assert bands["7_11"] == pytest.approx(0.0)
    assert bands["gt_11"] == pytest.approx(-4.0)


def test_total_calibration_metrics_winner_unchanged_by_total_only():
    pred_total_raw = np.array([8.0, 9.0, 10.0, 11.0])
    pred_total_cal = np.array([7.5, 9.0, 10.0, 12.0])
    pred_margin = np.array([1.0, -1.0, 2.0, -2.0])
    actual_total = np.array([7.5, 9.0, 10.0, 12.0])
    actual_margin = np.array([1.0, -1.0, 2.0, -2.0])
    before = total_calibration_metrics(
        pred_total_raw, pred_margin, actual_total, actual_margin
    )
    after = total_calibration_metrics(
        pred_total_cal, pred_margin, actual_total, actual_margin
    )
    assert before["winner_accuracy"] == after["winner_accuracy"]
    assert after["total_mae"] < before["total_mae"]


def test_isotonic_apply_clips_to_bounds():
    cal = TotalCalibration(
        type="isotonic",
        x_knots=[6.0, 8.0, 10.0, 12.0],
        y_knots=[2.0, 7.0, 9.0, 22.0],
        clip_min=3.0,
        clip_max=20.0,
    )
    assert cal.apply(5.0) == pytest.approx(3.0)
    assert cal.apply(15.0) == pytest.approx(20.0)
