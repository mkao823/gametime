"""MLB pregame ensemble helpers."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from gametime.pregame.baseball.prediction import EnsemblePrediction, MemberPrediction


def _validate_members(member_predictions: Sequence[MemberPrediction]) -> list[str]:
    if not member_predictions:
        raise ValueError("ensemble requires at least one member prediction")
    names = [pred.member for pred in member_predictions]
    expected_len = len(member_predictions[0].total)
    for pred in member_predictions:
        if len(pred.total) != expected_len or len(pred.margin) != expected_len:
            raise ValueError(
                f"Member '{pred.member}' prediction length mismatch in ensemble combine"
            )
    return names


def _weighted_sum(
    stacks: dict[str, np.ndarray],
    member_names: list[str],
    weights: dict[str, float],
) -> np.ndarray:
    weight_sum = sum(weights[name] for name in member_names)
    if weight_sum <= 0:
        raise ValueError("ensemble weights must sum to a positive value")
    out = np.zeros(len(stacks[member_names[0]]), dtype=float)
    for name in member_names:
        out += (weights[name] / weight_sum) * stacks[name]
    return out


def combine(
    member_predictions: Sequence[MemberPrediction],
    *,
    weights_total: dict[str, float],
    weights_margin: dict[str, float] | None = None,
) -> EnsemblePrediction:
    """Weighted average of member predictions (separate weights per target)."""
    member_names = _validate_members(member_predictions)
    pred_by_name = {pred.member: pred for pred in member_predictions}
    if weights_margin is None:
        weights_margin = weights_total

    total_stacks = {name: pred_by_name[name].total for name in member_names}
    margin_stacks = {name: pred_by_name[name].margin for name in member_names}
    return EnsemblePrediction(
        total=_weighted_sum(total_stacks, member_names, weights_total),
        margin=_weighted_sum(margin_stacks, member_names, weights_margin),
    )


def combine_equal(member_predictions: Sequence[MemberPrediction]) -> EnsemblePrediction:
    """Combine members with equal weights for total and margin."""
    member_names = _validate_members(member_predictions)
    equal = {name: 1.0 / len(member_names) for name in member_names}
    return combine(member_predictions, weights_total=equal, weights_margin=equal)


def _weight_balance_score(weights: dict[str, float], member_names: list[str]) -> float:
    """Higher score = more balanced blend (Shannon entropy of normalized weights)."""
    vals = np.array([max(weights.get(name, 0.0), 0.0) for name in member_names], dtype=float)
    total = float(vals.sum())
    if total <= 0:
        return 0.0
    p = vals[vals > 0] / total
    return float(-np.sum(p * np.log(p)))


def _grid_search_target(
    stacks: dict[str, np.ndarray],
    member_names: list[str],
    actual: np.ndarray,
    *,
    step: float,
    min_member_weight: float = 0.05,
) -> tuple[dict[str, float], float]:
    """Exhaustive grid on simplex (weights sum to 1) minimizing MAE for one target."""
    if len(actual) == 0:
        equal = {name: 1.0 / len(member_names) for name in member_names}
        return equal, float("nan")

    n = len(member_names)
    floor = max(float(min_member_weight), 0.0)
    grid = np.arange(0.0, 1.0 + step / 2, step)
    best_weights: dict[str, float] | None = None
    best_mae = float("inf")
    best_balance = -1.0

    def _consider(weights: dict[str, float], mae: float) -> None:
        nonlocal best_weights, best_mae, best_balance
        if any(weights[name] < floor - 1e-9 for name in member_names):
            return
        balance = _weight_balance_score(weights, member_names)
        if mae < best_mae - 1e-9:
            best_mae = mae
            best_weights = weights.copy()
            best_balance = balance
            return
        if abs(mae - best_mae) <= 1e-9 and (
            best_weights is None or balance > best_balance + 1e-12
        ):
            best_mae = mae
            best_weights = weights.copy()
            best_balance = balance

    def _recurse(idx: int, remaining: float, partial: list[float]) -> None:
        if idx == n - 1:
            w_last = remaining
            if w_last < -1e-9:
                return
            weights = {
                member_names[j]: float(partial[j]) for j in range(n - 1)
            }
            weights[member_names[n - 1]] = float(w_last)
            pred = sum(weights[name] * stacks[name] for name in member_names)
            _consider(weights, float(np.mean(np.abs(pred - actual))))
            return
        for w in grid:
            if w > remaining + 1e-9:
                continue
            partial.append(float(w))
            _recurse(idx + 1, remaining - w, partial)
            partial.pop()

    _recurse(0, 1.0, [])

    if best_weights is None:
        equal = {name: 1.0 / len(member_names) for name in member_names}
        return equal, float("nan")
    return best_weights, best_mae


def fit_weights(
    member_predictions: Sequence[MemberPrediction],
    actual_total: np.ndarray,
    actual_margin: np.ndarray,
    *,
    step: float = 0.1,
    min_member_weight: float = 0.05,
) -> tuple[dict[str, float], dict[str, float]]:
    """Tune per-target member weights on validation predictions only (grid search)."""
    member_names = _validate_members(member_predictions)
    pred_by_name = {pred.member: pred for pred in member_predictions}
    total_stacks = {name: pred_by_name[name].total for name in member_names}
    margin_stacks = {name: pred_by_name[name].margin for name in member_names}

    weights_total, _ = _grid_search_target(
        total_stacks,
        member_names,
        actual_total,
        step=step,
        min_member_weight=min_member_weight,
    )
    weights_margin, _ = _grid_search_target(
        margin_stacks,
        member_names,
        actual_margin,
        step=step,
        min_member_weight=min_member_weight,
    )
    return weights_total, weights_margin


def fit_weights_with_metrics(
    member_predictions: Sequence[MemberPrediction],
    actual_total: np.ndarray,
    actual_margin: np.ndarray,
    *,
    step: float = 0.1,
    min_member_weight: float = 0.05,
) -> tuple[dict[str, float], dict[str, float], dict[str, Any]]:
    """fit_weights plus validation metrics for the tuned weighted ensemble."""
    weights_total, weights_margin = fit_weights(
        member_predictions,
        actual_total,
        actual_margin,
        step=step,
        min_member_weight=min_member_weight,
    )
    weighted = combine(
        member_predictions,
        weights_total=weights_total,
        weights_margin=weights_margin,
    )
    val_metrics: dict[str, Any] = {
        "n": float(len(actual_total)),
        "total_mae": float(np.mean(np.abs(weighted.total - actual_total))),
        "margin_mae": float(np.mean(np.abs(weighted.margin - actual_margin))),
        "winner_accuracy": float(
            np.mean((weighted.margin > 0) == (actual_margin > 0))
        )
        if len(actual_margin)
        else None,
        "grid_step": step,
        "min_member_weight": min_member_weight,
    }
    return weights_total, weights_margin, val_metrics
