"""FastAPI application for MLB pregame predictions.

Run locally::

    uvicorn gametime.api.app:app --reload

Or::

    python -m gametime.api

Environment:

- ``GAMETIME_ROOT`` — repo root (default: package parent)
- ``GAMETIME_CONFIG`` — YAML path relative to root (default: ``configs/mlb.yaml``)

``GET /v1/game`` returns **404** when the requested matchup is not on the slate
for that date (same discovery as ``gametime-pregame-slate``). Ad-hoc matchups off
the official slate are not scored via this endpoint in v1.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Optional

from fastapi import FastAPI, HTTPException, Query, Request

from gametime.api.deps import (
    AppState,
    games_max_date,
    init_state,
    matchup_on_slate,
    relative_to_root,
    slate_for_date,
    to_game_prediction,
    validate_tricode,
)
from gametime.api.schemas import GamePrediction, HealthResponse, SlateResponse
from gametime.ingest.mlb import infer_season_start_year


def create_app(*, state: Optional[AppState] = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.gt = state or init_state()
        yield

    application = FastAPI(
        title="gametime MLB Predictions API",
        version="1.0.0",
        lifespan=lifespan,
    )

    @application.get("/health", response_model=HealthResponse)
    def health(request: Request) -> HealthResponse:
        gt: AppState = request.app.state.gt
        members = list(gt.predictor.ensemble_cfg.get("members", []))
        return HealthResponse(
            status="ok",
            games_max_date=games_max_date(gt.predictor.games),
            model_dir=relative_to_root(gt.model_dir, gt.settings.root),
            ensemble_members=members,
        )

    @application.get(
        "/v1/game",
        response_model=GamePrediction,
        response_model_exclude_none=True,
    )
    def predict_game(
        request: Request,
        home: Annotated[str, Query(description="Home team tricode.")],
        away: Annotated[str, Query(description="Away team tricode.")],
        date_param: Annotated[
            Optional[date],
            Query(alias="date", description="Slate date YYYY-MM-DD (default: today)."),
        ] = None,
        regular_season: Annotated[
            bool,
            Query(description="Regular-season slate only when true (default)."),
        ] = True,
        include_members: Annotated[
            bool,
            Query(description="Include per-member totals and margins."),
        ] = False,
    ) -> GamePrediction:
        gt: AppState = request.app.state.gt
        slate_date = date_param or date.today()
        try:
            home_tri = validate_tricode(home, allowed=gt.mlb_teams)
            away_tri = validate_tricode(away, allowed=gt.mlb_teams)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        if not matchup_on_slate(
            gt,
            home=home_tri,
            away=away_tri,
            slate_date=slate_date,
            regular_season=regular_season,
        ):
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Matchup {away_tri} @ {home_tri} not on slate for "
                    f"{slate_date.isoformat()}."
                ),
            )

        is_playoff = not regular_season
        pred = gt.predictor.predict(
            home=home_tri,
            away=away_tri,
            is_playoff=is_playoff,
            game_date=slate_date,
        )
        return GamePrediction(
            **to_game_prediction(pred, slate_date, include_members=include_members)
        )

    @application.get(
        "/v1/slate",
        response_model=SlateResponse,
        response_model_exclude_none=True,
    )
    def predict_slate(
        request: Request,
        date_param: Annotated[
            Optional[date],
            Query(alias="date", description="Slate date YYYY-MM-DD (default: today)."),
        ] = None,
        regular_season: Annotated[
            bool,
            Query(description="Regular-season slate only when true (default)."),
        ] = True,
        include_members: Annotated[
            bool,
            Query(description="Include per-member totals and margins per game."),
        ] = False,
    ) -> SlateResponse:
        gt: AppState = request.app.state.gt
        slate_date = date_param or date.today()
        season = infer_season_start_year(slate_date)
        is_playoff = not regular_season
        matchups = slate_for_date(gt, slate_date, regular_season=regular_season)
        games: list[GamePrediction] = []
        for m in matchups:
            pred = gt.predictor.predict(
                home=m["home"],
                away=m["away"],
                is_playoff=is_playoff,
                game_date=slate_date,
            )
            games.append(
                GamePrediction(
                    **to_game_prediction(
                        pred, slate_date, include_members=include_members
                    )
                )
            )
        return SlateResponse(
            date=slate_date.isoformat(),
            season_start_year=season,
            games=games,
        )

    return application


app = create_app()
