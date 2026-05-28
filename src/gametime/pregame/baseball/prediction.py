"""Prediction containers for MLB pregame ensemble members."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class MemberPrediction:
    member: str
    total: np.ndarray
    margin: np.ndarray


@dataclass(frozen=True)
class EnsemblePrediction:
    total: np.ndarray
    margin: np.ndarray
