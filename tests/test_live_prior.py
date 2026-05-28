"""Tests for pregame→live prior convergence."""
from __future__ import annotations

import pytest

from gametime.live.prior import LivePrior, prior_from_pregame_scored
from gametime.live.prior_demo import snapshot_at_pct


def test_prior_weight_at_tip_and_decay():
    prior = LivePrior(total=220.0, margin=5.0, source="test", decay_pct=0.5)
    assert prior.weight(0.0) == pytest.approx(1.0)
    assert prior.weight(0.5) == pytest.approx(0.0)
    assert prior.weight(1.0) == pytest.approx(0.0)


def test_prior_blend_starts_at_pregame():
    prior = LivePrior(total=200.0, margin=10.0, source="test", decay_pct=0.5)
    total, margin, w = prior.blend(lgb_total=250.0, lgb_margin=-20.0, pct_complete=0.0)
    assert w == pytest.approx(1.0)
    assert total == pytest.approx(200.0)
    assert margin == pytest.approx(10.0)


def test_prior_blend_ends_at_lgb():
    prior = LivePrior(total=200.0, margin=10.0, source="test", decay_pct=0.5)
    total, margin, w = prior.blend(lgb_total=250.0, lgb_margin=-20.0, pct_complete=0.6)
    assert w == pytest.approx(0.0)
    assert total == pytest.approx(250.0)
    assert margin == pytest.approx(-20.0)


def test_uncertainty_extends_decay():
    tight = LivePrior(total=220.0, margin=0.0, source="t", decay_pct=0.5, margin_band_width=12.0, blowout_prob=0.2)
    wide = LivePrior(total=220.0, margin=0.0, source="w", decay_pct=0.5, margin_band_width=36.0, blowout_prob=0.5)
    assert wide.effective_decay_pct() > tight.effective_decay_pct()
    assert wide.weight(0.25) > tight.weight(0.25)


def test_snapshot_at_pct_scores_track_prior():
    prior = LivePrior(total=220.0, margin=10.0, source="t")
    snap = snapshot_at_pct(
        game_id="x",
        home="OKC",
        away="SAS",
        pct_complete=0.5,
        prior=prior,
    )
    assert snap.home_score + snap.away_score == pytest.approx(110.0, abs=0.1)
    assert snap.home_score - snap.away_score == pytest.approx(5.0, abs=0.1)


def test_prior_from_pregame_scored():
    scored = {
        "total": 228.0,
        "margin_calibrated": 2.0,
        "margin_low": -10.0,
        "margin_high": 20.0,
        "blowout_prob": 0.4,
    }
    prior = prior_from_pregame_scored(scored)
    assert prior.total == 228.0
    assert prior.margin == 2.0
    assert prior.margin_band_width == pytest.approx(30.0)
