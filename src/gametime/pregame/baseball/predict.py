"""MLB pregame inference: ensemble members + weighted combine."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from gametime.pregame.baseball.ensemble import combine
from gametime.pregame.baseball.features import (
    build_inference_row,
    build_training_table,
)
from gametime.pregame.baseball.models.heuristic import HeuristicMember
from gametime.pregame.baseball.models.lgbm import LgbmMember
from gametime.pregame.baseball.models.poisson import (
    PoissonMember,
    _latest_poisson_rates,
    attach_poisson,
)
from gametime.pregame.baseball.models.runs_strength import (
    RunsStrengthMember,
    attach_runs_strength,
)
from gametime.pregame.baseball.prediction import MemberPrediction
from gametime.pregame.predict import PregamePrediction


@dataclass
class BaseballPregamePrediction:
    home_tricode: str
    away_tricode: str
    variant: str
    is_playoff: bool
    pred_total: float
    pred_margin: float
    pred_home_final: float
    pred_away_final: float
    winner_tricode: str
    win_prob_home: float
    home_form_n: int
    away_form_n: int
    ensemble_weights: Optional[dict[str, Any]] = None
    member_totals: Optional[dict[str, float]] = None
    member_margins: Optional[dict[str, float]] = None

    def as_dict(self) -> dict:
        return asdict(self)


def _logistic_home_win(margin: float, scale: float = 1.4) -> float:
    return 1.0 / (1.0 + math.exp(-margin / scale))


def _winner(home_tri: str, away_tri: str, margin: float) -> str:
    return home_tri if margin >= 0 else away_tri


def format_baseball_prediction(p: BaseballPregamePrediction) -> str:
    lines = [
        f"Matchup: {p.away_tricode} @ {p.home_tricode}  "
        f"({'playoff' if p.is_playoff else 'regular season'}, variant={p.variant})",
        f"Form n:  {p.home_tricode} last {p.home_form_n}  /  {p.away_tricode} last {p.away_form_n}",
        f"Predicted final: {p.away_tricode} {p.pred_away_final:.1f} @ "
        f"{p.home_tricode} {p.pred_home_final:.1f}  "
        f"(total {p.pred_total:.1f}, margin {p.pred_margin:+.1f})",
        f"Predicted winner: {p.winner_tricode}  "
        f"(home win prob {p.win_prob_home * 100:.1f}%)",
    ]
    if p.member_totals and p.member_margins:
        for name in sorted(p.member_totals):
            lines.append(
                f"  Member {name}: total {p.member_totals[name]:.1f}, "
                f"margin {p.member_margins[name]:+.1f}"
            )
    return "\n".join(lines)


class BaseballPregamePredictor:
    """Load MLB pregame ensemble artifacts and score one matchup."""

    def __init__(
        self,
        model_dir: str | Path,
        games_path: str | Path,
        *,
        form_window: int = 10,
        runs_strength_window: int = 30,
        train_seasons: list[int],
        train_seasontypes: list[str] | None = None,
    ) -> None:
        model_dir = Path(model_dir)
        self.model_dir = model_dir
        self.games = pd.read_parquet(games_path)
        self.form_window = form_window
        self.runs_strength_window = runs_strength_window

        with (model_dir / "ensemble.json").open() as f:
            self.ensemble_cfg: dict[str, Any] = json.load(f)
        meta_path = model_dir / "meta.json"
        if meta_path.exists():
            with meta_path.open() as f:
                meta = json.load(f)
            self.form_window = int(meta.get("form_window", form_window))
            self.runs_strength_window = int(
                meta.get("runs_strength_window", runs_strength_window)
            )

        self.lgbm = LgbmMember.load(model_dir)
        self.heuristic = HeuristicMember()
        self.runs_strength = RunsStrengthMember()
        self.poisson = PoissonMember()

        table = build_training_table(self.games, form_window=self.form_window)
        table = attach_runs_strength(
            table, self.games, window=self.runs_strength_window
        )
        table = attach_poisson(table, self.games)
        seasontypes = train_seasontypes or ["rg"]
        train_df = table[
            table["season_start_year"].isin(train_seasons)
            & table["seasontype"].isin(seasontypes)
        ]
        if len(train_df) == 0:
            raise ValueError(
                "No train rows for member refit; check train_seasons / train_seasontypes"
            )
        self.heuristic.fit(train_df)
        self.runs_strength.fit(train_df)
        self.poisson.fit(train_df)

        self._weights_total = self.ensemble_cfg["weights"]["total"]
        self._weights_margin = self.ensemble_cfg["weights"]["margin"]
        self._winner_mode = self.ensemble_cfg.get("winner_mode", "sign_margin")

    def _form_n(self, team_games: pd.DataFrame, team: str) -> int:
        from gametime.pregame.baseball.features import _form_game_count

        return _form_game_count(team_games, team.upper(), self.form_window)

    def predict(
        self,
        *,
        home: str,
        away: str,
        is_playoff: bool = False,
    ) -> BaseballPregamePrediction:
        home, away = home.upper(), away.upper()
        row_df = build_inference_row(
            home=home,
            away=away,
            games=self.games,
            form_window=self.form_window,
            runs_strength_window=self.runs_strength_window,
            is_playoff=is_playoff,
        )
        row_df = row_df.assign(**_latest_poisson_rates(self.games, home=home, away=away))

        member_preds: list[MemberPrediction] = [
            self.lgbm.predict(row_df),
            self.heuristic.predict(row_df),
            self.runs_strength.predict(row_df),
            self.poisson.predict(row_df),
        ]
        ensemble = combine(
            member_preds,
            weights_total=self._weights_total,
            weights_margin=self._weights_margin,
        )
        total = float(ensemble.total[0])
        margin = float(ensemble.margin[0])

        if self._winner_mode == "sign_margin":
            winner = _winner(home, away, margin)
            win_prob = _logistic_home_win(margin)
        else:
            proba = float(self.lgbm.predict_winner_proba(row_df).iloc[0])
            winner = home if proba >= 0.5 else away
            win_prob = proba

        from gametime.pregame.baseball.features import _rolling_team_stats, _team_game_rows

        team_games = _rolling_team_stats(_team_game_rows(self.games), self.form_window)
        home_form_n = self._form_n(team_games, home)
        away_form_n = self._form_n(team_games, away)

        member_totals = {p.member: float(p.total[0]) for p in member_preds}
        member_margins = {p.member: float(p.margin[0]) for p in member_preds}

        home_final = (total + margin) / 2.0
        away_final = (total - margin) / 2.0
        return BaseballPregamePrediction(
            home_tricode=home,
            away_tricode=away,
            variant="ensemble",
            is_playoff=is_playoff,
            pred_total=total,
            pred_margin=margin,
            pred_home_final=home_final,
            pred_away_final=away_final,
            winner_tricode=winner,
            win_prob_home=win_prob,
            home_form_n=home_form_n,
            away_form_n=away_form_n,
            ensemble_weights=self.ensemble_cfg.get("weights"),
            member_totals=member_totals,
            member_margins=member_margins,
        )

    def to_pregame_prediction(self, p: BaseballPregamePrediction) -> PregamePrediction:
        """Adapter for basketball logging helpers."""
        return PregamePrediction(
            home_tricode=p.home_tricode,
            away_tricode=p.away_tricode,
            variant=p.variant,
            is_playoff=p.is_playoff,
            elo_home=0.0,
            elo_away=0.0,
            pred_total=p.pred_total,
            pred_margin=p.pred_margin,
            pred_home_final=p.pred_home_final,
            pred_away_final=p.pred_away_final,
            winner_tricode=p.winner_tricode,
            win_prob_home=p.win_prob_home,
            home_form_n=p.home_form_n,
            away_form_n=p.away_form_n,
        )
