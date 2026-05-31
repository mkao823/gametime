"""Post-training margin calibration and blowout-aware stretching."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np


@dataclass
class MarginCalibration:
    """Affine calibration + optional stretch when blowout classifier fires."""

    slope: float = 1.0
    intercept: float = 0.0
    blowout_stretch: float = 0.35
    blowout_prob_gate: float = 0.35
    blowout_margin_pts: float = 10.0

    def apply(self, margin: float, blowout_prob: float) -> float:
        m = self.slope * float(margin) + self.intercept
        if blowout_prob >= self.blowout_prob_gate:
            stretch = 1.0 + self.blowout_stretch * float(blowout_prob)
            m = float(np.sign(m) * abs(m) * stretch)
        return m

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "MarginCalibration":
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})


def fit_margin_calibration(
    pred_margin: np.ndarray,
    actual_margin: np.ndarray,
    *,
    blowout_margin_pts: float = 10.0,
    blowout_prob_gate: float = 0.35,
) -> MarginCalibration:
    pred = np.asarray(pred_margin, dtype=float)
    actual = np.asarray(actual_margin, dtype=float)
    if len(pred) < 10:
        return MarginCalibration(blowout_prob_gate=blowout_prob_gate, blowout_margin_pts=blowout_margin_pts)

    slope, intercept = np.polyfit(pred, actual, 1)
    blowout_mask = np.abs(actual) >= blowout_margin_pts
    stretch = 0.35
    if blowout_mask.sum() >= 5:
        denom = np.maximum(np.abs(pred[blowout_mask]), 1.0)
        ratios = np.abs(actual[blowout_mask]) / denom
        stretch = float(np.clip(np.median(ratios) - 1.0, 0.0, 1.5))

    return MarginCalibration(
        slope=float(slope),
        intercept=float(intercept),
        blowout_stretch=stretch,
        blowout_prob_gate=blowout_prob_gate,
        blowout_margin_pts=blowout_margin_pts,
    )


def save_calibration(cal: MarginCalibration, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cal.to_dict(), indent=2))


def load_calibration(path: Path) -> MarginCalibration:
    return MarginCalibration.from_dict(json.loads(path.read_text()))


@dataclass
class MarginBandCalibration:
    """Symmetric scale on quantile half-width to hit target coverage on PO validation."""

    scale: float = 1.0
    target_coverage: float = 0.80
    n_fit_games: int = 0
    coverage_before: float = 0.0
    coverage_after: float = 0.0
    mean_width_before: float = 0.0
    mean_width_after: float = 0.0
    fit_seasontype: str = "po"

    def apply(self, margin_low: float, margin_high: float) -> tuple[float, float]:
        center = 0.5 * (float(margin_low) + float(margin_high))
        half = 0.5 * (float(margin_high) - float(margin_low))
        half = max(half, 0.5)
        half *= self.scale
        return center - half, center + half

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "MarginBandCalibration":
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})


def _band_metrics(
    actual: np.ndarray,
    low: np.ndarray,
    high: np.ndarray,
) -> tuple[float, float]:
    actual = np.asarray(actual, dtype=float)
    low = np.asarray(low, dtype=float)
    high = np.asarray(high, dtype=float)
    if len(actual) == 0:
        return 0.0, 0.0
    coverage = float(np.mean((actual >= low) & (actual <= high)))
    width = float(np.mean(high - low))
    return coverage, width


def fit_margin_band_calibration(
    margin_low: np.ndarray,
    margin_high: np.ndarray,
    actual_margin: np.ndarray,
    *,
    target_coverage: float = 0.80,
    min_scale: float = 0.35,
    max_scale: float = 1.25,
) -> MarginBandCalibration:
    """Find the smallest scale factor s such that coverage >= target on the fit set."""
    low = np.asarray(margin_low, dtype=float)
    high = np.asarray(margin_high, dtype=float)
    actual = np.asarray(actual_margin, dtype=float)
    cov_before, width_before = _band_metrics(actual, low, high)

    if len(actual) < 8:
        return MarginBandCalibration(
            scale=1.0,
            target_coverage=target_coverage,
            n_fit_games=int(len(actual)),
            coverage_before=cov_before,
            coverage_after=cov_before,
            mean_width_before=width_before,
            mean_width_after=width_before,
        )

    center = 0.5 * (low + high)
    half = np.maximum(0.5 * (high - low), 0.5)

    def coverage_at(scale: float) -> float:
        lo = center - scale * half
        hi = center + scale * half
        return float(np.mean((actual >= lo) & (actual <= hi)))

    if coverage_at(1.0) < target_coverage:
        if coverage_at(max_scale) < target_coverage:
            chosen = max_scale
        else:
            lo_s, hi_s = 1.0, max_scale
            chosen = max_scale
            for _ in range(32):
                mid = 0.5 * (lo_s + hi_s)
                if coverage_at(mid) >= target_coverage:
                    chosen = mid
                    hi_s = mid
                else:
                    lo_s = mid
    elif coverage_at(min_scale) >= target_coverage:
        chosen = min_scale
    else:
        lo_s, hi_s = min_scale, 1.0
        chosen = 1.0
        for _ in range(32):
            mid = 0.5 * (lo_s + hi_s)
            if coverage_at(mid) >= target_coverage:
                chosen = mid
                hi_s = mid
            else:
                lo_s = mid

    lo_scaled = center - chosen * half
    hi_scaled = center + chosen * half
    cov_after, width_after = _band_metrics(actual, lo_scaled, hi_scaled)

    return MarginBandCalibration(
        scale=float(chosen),
        target_coverage=target_coverage,
        n_fit_games=int(len(actual)),
        coverage_before=cov_before,
        coverage_after=cov_after,
        mean_width_before=width_before,
        mean_width_after=width_after,
    )


def save_band_calibration(cal: MarginBandCalibration, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cal.to_dict(), indent=2))


def load_band_calibration(path: Path) -> MarginBandCalibration:
    return MarginBandCalibration.from_dict(json.loads(path.read_text()))


@dataclass
class TotalCalibration:
    """Post-ensemble affine or isotonic mapping for game totals."""

    type: str = "affine"
    slope: float = 1.0
    intercept: float = 0.0
    x_knots: list[float] | None = None
    y_knots: list[float] | None = None
    clip_min: float = 3.0
    clip_max: float = 20.0
    fit_split: str = "val"
    val_season: int | None = None
    n_fit: int = 0

    def apply(self, total_raw: float | np.ndarray) -> float | np.ndarray:
        raw = np.asarray(total_raw, dtype=float)
        if self.type == "isotonic" and self.x_knots and self.y_knots:
            x = np.asarray(self.x_knots, dtype=float)
            y = np.asarray(self.y_knots, dtype=float)
            cal = np.interp(raw, x, y)
        else:
            cal = self.slope * raw + self.intercept
        cal = np.clip(cal, self.clip_min, self.clip_max)
        if np.isscalar(total_raw):
            return float(cal)
        return cal

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TotalCalibration":
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})


def _fit_affine_total(
    pred: np.ndarray, actual: np.ndarray
) -> tuple[float, float]:
    slope, intercept = np.polyfit(pred, actual, 1)
    return float(slope), float(intercept)


def _fit_isotonic_total(
    pred: np.ndarray,
    actual: np.ndarray,
    *,
    clip_min: float = 3.0,
    clip_max: float = 20.0,
) -> tuple[list[float], list[float]]:
    from sklearn.isotonic import IsotonicRegression

    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(pred, actual)
    x_knots = iso.X_thresholds_.tolist()
    y_knots = np.clip(iso.y_thresholds_, clip_min, clip_max).tolist()
    return x_knots, y_knots


def fit_total_calibration(
    pred_total: np.ndarray,
    actual_total: np.ndarray,
    *,
    val_season: int | None = None,
    clip_min: float = 3.0,
    clip_max: float = 20.0,
) -> TotalCalibration:
    """Fit affine total calibration; fall back to isotonic if affine does not help."""
    pred = np.asarray(pred_total, dtype=float)
    actual = np.asarray(actual_total, dtype=float)
    n_fit = int(len(pred))
    if n_fit < 10:
        return TotalCalibration(
            fit_split="val",
            val_season=val_season,
            n_fit=n_fit,
            clip_min=clip_min,
            clip_max=clip_max,
        )

    mae_before = float(np.mean(np.abs(pred - actual)))
    slope, intercept = _fit_affine_total(pred, actual)
    affine = TotalCalibration(
        type="affine",
        slope=slope,
        intercept=intercept,
        fit_split="val",
        val_season=val_season,
        n_fit=n_fit,
        clip_min=clip_min,
        clip_max=clip_max,
    )
    mae_affine = float(np.mean(np.abs(affine.apply(pred) - actual)))

    x_knots, y_knots = _fit_isotonic_total(
        pred, actual, clip_min=clip_min, clip_max=clip_max
    )
    isotonic = TotalCalibration(
        type="isotonic",
        x_knots=x_knots,
        y_knots=y_knots,
        fit_split="val",
        val_season=val_season,
        n_fit=n_fit,
        clip_min=clip_min,
        clip_max=clip_max,
    )
    mae_isotonic = float(np.mean(np.abs(isotonic.apply(pred) - actual)))

    if mae_isotonic + 1e-9 < mae_affine and mae_isotonic + 1e-9 < mae_before:
        return isotonic
    if mae_affine + 1e-9 < mae_before:
        return affine
    return TotalCalibration(
        fit_split="val",
        val_season=val_season,
        n_fit=n_fit,
        clip_min=clip_min,
        clip_max=clip_max,
    )


def save_total_calibration(cal: TotalCalibration, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cal.to_dict(), indent=2))


def load_total_calibration(path: Path) -> TotalCalibration:
    return TotalCalibration.from_dict(json.loads(path.read_text()))


def load_total_calibration_if_present(model_dir: Path) -> TotalCalibration | None:
    path = Path(model_dir) / "total_calibration.json"
    return load_total_calibration(path) if path.exists() else None


def total_band_bias(
    pred_total: np.ndarray,
    actual_total: np.ndarray,
) -> dict[str, float | None]:
    """Mean signed error by actual-total bands (<7, 7–11, >11)."""
    pred = np.asarray(pred_total, dtype=float)
    actual = np.asarray(actual_total, dtype=float)
    bands = {
        "lt_7": actual < 7.0,
        "7_11": (actual >= 7.0) & (actual <= 11.0),
        "gt_11": actual > 11.0,
    }
    out: dict[str, float | None] = {}
    for name, mask in bands.items():
        if mask.sum() == 0:
            out[name] = None
        else:
            out[name] = float(np.mean(pred[mask] - actual[mask]))
    return out


def total_calibration_metrics(
    pred_total: np.ndarray,
    pred_margin: np.ndarray,
    actual_total: np.ndarray,
    actual_margin: np.ndarray,
) -> dict[str, float | dict[str, float | None]]:
    pred_t = np.asarray(pred_total, dtype=float)
    pred_m = np.asarray(pred_margin, dtype=float)
    actual_t = np.asarray(actual_total, dtype=float)
    actual_m = np.asarray(actual_margin, dtype=float)
    if len(pred_t) == 0:
        return {}
    return {
        "n": float(len(pred_t)),
        "total_mae": float(np.mean(np.abs(pred_t - actual_t))),
        "margin_mae": float(np.mean(np.abs(pred_m - actual_m))),
        "bias_total": float(np.mean(pred_t - actual_t)),
        "winner_accuracy": float(np.mean((pred_m > 0) == (actual_m > 0))),
        "band_bias": total_band_bias(pred_t, actual_t),
    }
