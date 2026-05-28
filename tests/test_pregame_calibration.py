"""Tests for pregame margin calibration and PO interaction features."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from gametime.pregame.calibration import (
    MarginBandCalibration,
    MarginCalibration,
    fit_margin_band_calibration,
    fit_margin_calibration,
    load_calibration,
    save_calibration,
)
from gametime.pregame.features import FEATURE_COLUMNS, add_po_interaction_features


def test_fit_margin_calibration_affine():
    pred = np.array([2.0, 4.0, 6.0, 8.0, 10.0, -2.0, -4.0, -6.0, -8.0, -10.0])
    actual = pred * 1.5 + 1.0
    cal = fit_margin_calibration(pred, actual, blowout_margin_pts=10.0)
    assert cal.slope == pytest.approx(1.5, abs=0.05)
    assert cal.intercept == pytest.approx(1.0, abs=0.05)


def test_margin_calibration_blowout_stretch():
    cal = MarginCalibration(
        slope=1.0,
        intercept=0.0,
        blowout_stretch=0.5,
        blowout_prob_gate=0.35,
    )
    assert cal.apply(5.0, 0.2) == pytest.approx(5.0)
    stretched = cal.apply(5.0, 0.5)
    assert stretched == pytest.approx(5.0 * (1.0 + 0.5 * 0.5))
    assert cal.apply(-5.0, 0.5) == pytest.approx(-stretched)


def test_calibration_save_load(tmp_path: Path):
    cal = MarginCalibration(slope=1.2, intercept=-0.5, blowout_stretch=0.4)
    path = tmp_path / "calibration.json"
    save_calibration(cal, path)
    loaded = load_calibration(path)
    assert loaded.slope == cal.slope
    assert loaded.intercept == cal.intercept
    assert loaded.blowout_stretch == cal.blowout_stretch
    assert json.loads(path.read_text())["blowout_prob_gate"] == 0.35


def test_po_interaction_features():
    row = pd.Series(
        {
            "elo_diff": 100.0,
            "home_form_margin": 5.0,
            "away_form_margin": -2.0,
            "series_game_n": 3.0,
            "is_playoff": 1.0,
            "home_po_game_n": 8.0,
            "away_po_game_n": 6.0,
        }
    )
    out = add_po_interaction_features(row)
    assert out["series_x_elo_diff"] == pytest.approx(3.0)
    assert out["series_x_form_margin"] == pytest.approx(21.0)
    assert out["home_po_x_elo"] == pytest.approx(8.0)
    assert out["away_po_x_elo"] == pytest.approx(-6.0)


def test_fit_margin_band_calibration_narrows_while_covering():
    actual = np.array([-15.0, -5.0, 0.0, 5.0, 15.0, 20.0, -20.0, 8.0])
    low = actual - 20.0
    high = actual + 20.0
    cal = fit_margin_band_calibration(low, high, actual, target_coverage=0.80)
    assert cal.scale < 1.0
    assert cal.coverage_after >= 0.80
    assert cal.mean_width_after < cal.mean_width_before


def test_margin_band_calibration_apply():
    cal = MarginBandCalibration(scale=0.5)
    lo, hi = cal.apply(-10.0, 10.0)
    assert lo == pytest.approx(-5.0)
    assert hi == pytest.approx(5.0)


def test_po_interaction_features_in_feature_columns():
    assert "series_x_elo_diff" in FEATURE_COLUMNS
    assert "home_po_x_elo" in FEATURE_COLUMNS
