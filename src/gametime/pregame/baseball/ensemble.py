"""MLB pregame ensemble helpers."""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from gametime.pregame.baseball.prediction import EnsemblePrediction, MemberPrediction


def combine_equal(member_predictions: Sequence[MemberPrediction]) -> EnsemblePrediction:
    """Combine members with equal weights for total and margin."""
    if not member_predictions:
        raise ValueError("combine_equal requires at least one member prediction")

    expected_len = len(member_predictions[0].total)
    for pred in member_predictions:
        if len(pred.total) != expected_len or len(pred.margin) != expected_len:
            raise ValueError(
                f"Member '{pred.member}' prediction length mismatch in combine_equal"
            )

    total_stack = np.vstack([pred.total for pred in member_predictions])
    margin_stack = np.vstack([pred.margin for pred in member_predictions])
    return EnsemblePrediction(total=np.mean(total_stack, axis=0), margin=np.mean(margin_stack, axis=0))
