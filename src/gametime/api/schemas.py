"""Pydantic response models for Predictions API v1 (OpenAPI source of truth)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    """Liveness and artifact freshness metadata."""

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "status": "ok",
            "games_max_date": "2026-06-08",
            "model_dir": "models/mlb/pregame",
            "ensemble_members": ["lgbm", "heuristic", "runs_strength"],
        }
    })

    status: str = Field(description="Service status; 'ok' when predictor loaded.")
    games_max_date: Optional[str] = Field(
        None, description="Latest game_date in games.parquet (ISO date)."
    )
    model_dir: str = Field(description="Ensemble artifact directory (relative to repo root).")
    ensemble_members: list[str] = Field(
        description="Member keys from ensemble.json (blend order)."
    )


class GamePrediction(BaseModel):
    """Stable v1 game prediction payload."""

    model_config = ConfigDict(exclude_none=True)

    home: str = Field(description="Home team tricode.")
    away: str = Field(description="Away team tricode.")
    date: str = Field(description="Slate calendar date (ISO YYYY-MM-DD).")
    pred_total: float = Field(description="Ensemble predicted total runs.")
    pred_margin: float = Field(description="Predicted home margin (positive = home favored).")
    pred_home_final: float
    pred_away_final: float
    winner: str = Field(description="Predicted winner tricode.")
    win_prob_home: float = Field(ge=0.0, le=1.0)
    is_playoff: bool
    home_form_n: int
    away_form_n: int
    member_totals: Optional[dict[str, float]] = Field(
        None, description="Per-member total runs; present when include_members=true."
    )
    member_margins: Optional[dict[str, float]] = Field(
        None, description="Per-member home margin; present when include_members=true."
    )
    start_time: Optional[str] = Field(
        None, description="Scheduled first pitch (ISO-8601 UTC from MLB Stats API gameDate)."
    )


class SlateResponse(BaseModel):
    """All matchups predicted for one calendar date."""

    date: str
    season_start_year: int
    games: list[GamePrediction]
