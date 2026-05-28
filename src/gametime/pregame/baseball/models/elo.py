"""Elo member: causal team ratings from game results → margin and implied total."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from gametime.pregame.baseball.features import LEAGUE_RPG
from gametime.pregame.baseball.models.base import BaseballMemberModel
from gametime.pregame.baseball.prediction import MemberPrediction

DEFAULT_BASE = 1500.0
DEFAULT_K = 4.0
DEFAULT_HOME_ADV_RUNS = 0.15
DEFAULT_SEASON_REGRESSION = 0.25
DEFAULT_MARGIN_ELO_SCALE = 50.0
OFFDEF_SCALE = 18.0
OFFDEF_K = 0.15

ELO_COLUMNS = [
    "home_elo_pre",
    "away_elo_pre",
    "home_off_elo_pre",
    "away_off_elo_pre",
    "home_def_elo_pre",
    "away_def_elo_pre",
]


@dataclass
class BaseballEloParams:
    base_rating: float = DEFAULT_BASE
    k: float = DEFAULT_K
    home_adv_runs: float = DEFAULT_HOME_ADV_RUNS
    season_regression: float = DEFAULT_SEASON_REGRESSION
    margin_elo_scale: float = DEFAULT_MARGIN_ELO_SCALE


def _expected(home_rating: float, away_rating: float, hca_elo: float) -> float:
    diff = (home_rating + hca_elo) - away_rating
    return 1.0 / (1.0 + 10.0 ** (-diff / 400.0))


def _mov_multiplier_runs(margin_runs: float, rating_diff: float) -> float:
    abs_margin = abs(margin_runs)
    return ((abs_margin + 1.5) ** 0.8) / (4.0 + 0.01 * abs(rating_diff))


def _hca_elo(home_adv_runs: float, margin_elo_scale: float) -> float:
    return home_adv_runs * margin_elo_scale


@dataclass
class BaseballEloState:
    """Win/loss team strength (538-style) for margin."""

    params: BaseballEloParams = field(default_factory=BaseballEloParams)
    ratings: dict[str, float] = field(default_factory=dict)
    last_season: dict[str, int] = field(default_factory=dict)

    def rating(self, team: str) -> float:
        return self.ratings.get(team, self.params.base_rating)

    def _begin_season(self, team: str, season: int) -> None:
        prev = self.last_season.get(team)
        if prev is None or prev == season:
            self.last_season[team] = season
            return
        if season > prev:
            current = self.ratings.get(team, self.params.base_rating)
            self.ratings[team] = (
                current
                - self.params.season_regression
                * (current - self.params.base_rating)
            )
            self.last_season[team] = season

    def update(
        self,
        *,
        season: int,
        home: str,
        away: str,
        home_runs: float,
        away_runs: float,
    ) -> tuple[float, float]:
        self._begin_season(home, season)
        self._begin_season(away, season)
        home_pre = self.rating(home)
        away_pre = self.rating(away)
        hca = _hca_elo(self.params.home_adv_runs, self.params.margin_elo_scale)
        exp_home = _expected(home_pre, away_pre, hca)
        if home_runs > away_runs:
            actual_home = 1.0
        elif home_runs < away_runs:
            actual_home = 0.0
        else:
            actual_home = 0.5
        margin = home_runs - away_runs
        rating_diff = (home_pre + hca) - away_pre
        if home_runs < away_runs:
            rating_diff = -rating_diff
        mov = _mov_multiplier_runs(margin, rating_diff)
        delta = self.params.k * mov * (actual_home - exp_home)
        self.ratings[home] = home_pre + delta
        self.ratings[away] = away_pre - delta
        return home_pre, away_pre

    def to_dict(self) -> dict:
        return {
            "params": asdict(self.params),
            "ratings": dict(self.ratings),
            "last_season": dict(self.last_season),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BaseballEloState":
        params = BaseballEloParams(**data.get("params", {}))
        state = cls(params=params)
        state.ratings = dict(data.get("ratings", {}))
        state.last_season = {k: int(v) for k, v in data.get("last_season", {}).items()}
        return state


@dataclass
class BaseballOffDefState:
    """Offensive / defensive run strength for implied totals."""

    params: BaseballEloParams = field(default_factory=BaseballEloParams)
    off_ratings: dict[str, float] = field(default_factory=dict)
    def_ratings: dict[str, float] = field(default_factory=dict)
    last_season: dict[str, int] = field(default_factory=dict)

    def off_rating(self, team: str) -> float:
        return self.off_ratings.get(team, self.params.base_rating)

    def def_rating(self, team: str) -> float:
        return self.def_ratings.get(team, self.params.base_rating)

    def _regress_season(self, team: str, season: int) -> None:
        prev = self.last_season.get(team)
        if prev is None or prev == season:
            self.last_season[team] = season
            return
        if season > prev:
            for bucket in (self.off_ratings, self.def_ratings):
                current = bucket.get(team, self.params.base_rating)
                bucket[team] = (
                    current
                    - self.params.season_regression * (current - self.params.base_rating)
                )
            self.last_season[team] = season

    def expected_home_runs(self, home: str, away: str) -> float:
        return (
            LEAGUE_RPG
            + (self.off_rating(home) - self.params.base_rating) / OFFDEF_SCALE
            - (self.def_rating(away) - self.params.base_rating) / OFFDEF_SCALE
            + self.params.home_adv_runs
        )

    def expected_away_runs(self, home: str, away: str) -> float:
        return (
            LEAGUE_RPG
            + (self.off_rating(away) - self.params.base_rating) / OFFDEF_SCALE
            - (self.def_rating(home) - self.params.base_rating) / OFFDEF_SCALE
        )

    def update_game(
        self,
        *,
        season: int,
        home: str,
        away: str,
        home_runs: float,
        away_runs: float,
    ) -> tuple[float, float, float, float]:
        for team in (home, away):
            self._regress_season(team, season)
        h_off_pre = self.off_rating(home)
        a_off_pre = self.off_rating(away)
        h_def_pre = self.def_rating(home)
        a_def_pre = self.def_rating(away)
        exp_h = self.expected_home_runs(home, away)
        exp_a = self.expected_away_runs(home, away)
        self.off_ratings[home] = h_off_pre + OFFDEF_K * (home_runs - exp_h)
        self.def_ratings[away] = a_def_pre - OFFDEF_K * (home_runs - exp_h)
        self.off_ratings[away] = a_off_pre + OFFDEF_K * (away_runs - exp_a)
        self.def_ratings[home] = h_def_pre - OFFDEF_K * (away_runs - exp_a)
        return h_off_pre, a_off_pre, h_def_pre, a_def_pre

    def to_dict(self) -> dict:
        return {
            "params": asdict(self.params),
            "off_ratings": dict(self.off_ratings),
            "def_ratings": dict(self.def_ratings),
            "last_season": dict(self.last_season),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BaseballOffDefState":
        params = BaseballEloParams(**data.get("params", {}))
        state = cls(params=params)
        state.off_ratings = dict(data.get("off_ratings", {}))
        state.def_ratings = dict(data.get("def_ratings", {}))
        state.last_season = {k: int(v) for k, v in data.get("last_season", {}).items()}
        return state


def _game_level(games: pd.DataFrame) -> pd.DataFrame:
    g = games.sort_values(["game_date", "game_id"]).reset_index(drop=True)
    return g[
        [
            "game_id",
            "game_date",
            "season_start_year",
            "home_team",
            "away_team",
            "home_runs",
            "away_runs",
        ]
    ]


def fit_baseball_elo(
    games: pd.DataFrame,
    params: Optional[BaseballEloParams] = None,
) -> tuple[pd.DataFrame, BaseballEloState, BaseballOffDefState]:
    """Walk games causally; return per-game pre-ratings and final states."""
    params = params or BaseballEloParams()
    win_state = BaseballEloState(params=params)
    offdef_state = BaseballOffDefState(params=params)
    games_sorted = _game_level(games)

    home_elo, away_elo = [], []
    h_off, a_off, h_def, a_def = [], [], [], []
    for row in games_sorted.itertuples(index=False):
        h_pre, a_pre = win_state.update(
            season=int(row.season_start_year),
            home=str(row.home_team),
            away=str(row.away_team),
            home_runs=float(row.home_runs),
            away_runs=float(row.away_runs),
        )
        ho, ao, hd, ad = offdef_state.update_game(
            season=int(row.season_start_year),
            home=str(row.home_team),
            away=str(row.away_team),
            home_runs=float(row.home_runs),
            away_runs=float(row.away_runs),
        )
        home_elo.append(h_pre)
        away_elo.append(a_pre)
        h_off.append(ho)
        a_off.append(ao)
        h_def.append(hd)
        a_def.append(ad)

    out = games_sorted.copy()
    out["home_elo_pre"] = home_elo
    out["away_elo_pre"] = away_elo
    out["home_off_elo_pre"] = h_off
    out["away_off_elo_pre"] = a_off
    out["home_def_elo_pre"] = h_def
    out["away_def_elo_pre"] = a_def
    return out, win_state, offdef_state


def attach_elo(
    table: pd.DataFrame,
    games: pd.DataFrame,
    *,
    params: Optional[BaseballEloParams] = None,
) -> pd.DataFrame:
    """Merge causal pre-game Elo columns onto the training table."""
    params = params or BaseballEloParams()
    rated, _, _ = fit_baseball_elo(games, params=params)
    ctx = rated.set_index("game_id")
    out = table.copy()
    for col in ELO_COLUMNS:
        out[col] = out["game_id"].map(ctx[col]).fillna(params.base_rating)
    return out


def _latest_elo_columns(
    games: pd.DataFrame,
    *,
    home: str,
    away: str,
    params: Optional[BaseballEloParams] = None,
) -> dict[str, float]:
    """Pre-game ratings for the next matchup (all prior games in ``games``)."""
    params = params or BaseballEloParams()
    _, win_state, offdef_state = fit_baseball_elo(games, params=params)
    return {
        "home_elo_pre": win_state.rating(home),
        "away_elo_pre": win_state.rating(away),
        "home_off_elo_pre": offdef_state.off_rating(home),
        "away_off_elo_pre": offdef_state.off_rating(away),
        "home_def_elo_pre": offdef_state.def_rating(home),
        "away_def_elo_pre": offdef_state.def_rating(away),
    }


def _raw_predictions(df: pd.DataFrame, params: BaseballEloParams) -> tuple[np.ndarray, np.ndarray]:
    elo_diff = df["home_elo_pre"].to_numpy() - df["away_elo_pre"].to_numpy()
    raw_margin = elo_diff / params.margin_elo_scale + params.home_adv_runs
    home_runs = (
        LEAGUE_RPG
        + (df["home_off_elo_pre"].to_numpy() - params.base_rating) / OFFDEF_SCALE
        - (df["away_def_elo_pre"].to_numpy() - params.base_rating) / OFFDEF_SCALE
        + params.home_adv_runs
    )
    away_runs = (
        LEAGUE_RPG
        + (df["away_off_elo_pre"].to_numpy() - params.base_rating) / OFFDEF_SCALE
        - (df["home_def_elo_pre"].to_numpy() - params.base_rating) / OFFDEF_SCALE
    )
    raw_total = home_runs + away_runs
    return raw_total, raw_margin


def save_member_state(
    path: Path,
    *,
    win_state: BaseballEloState,
    offdef_state: BaseballOffDefState,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"win": win_state.to_dict(), "offdef": offdef_state.to_dict()},
            indent=2,
        )
    )


def load_member_state(path: Path) -> tuple[BaseballEloState, BaseballOffDefState]:
    data = json.loads(path.read_text())
    return (
        BaseballEloState.from_dict(data["win"]),
        BaseballOffDefState.from_dict(data["offdef"]),
    )


class EloMember(BaseballMemberModel):
    """538-style Elo on runs/margin with off/def implied totals."""

    name = "elo"

    def __init__(self, params: Optional[BaseballEloParams] = None) -> None:
        self.params = params or BaseballEloParams()
        self._total_bias = 0.0
        self._margin_bias = 0.0

    def fit(self, train_df: pd.DataFrame) -> None:
        raw_total, raw_margin = _raw_predictions(train_df, self.params)
        self._total_bias = float(train_df["total_final"].mean() - np.mean(raw_total))
        self._margin_bias = float(train_df["margin_final"].mean() - np.mean(raw_margin))

    def predict(self, df: pd.DataFrame) -> MemberPrediction:
        raw_total, raw_margin = _raw_predictions(df, self.params)
        total = raw_total + self._total_bias
        margin = raw_margin + self._margin_bias
        return MemberPrediction(member=self.name, total=total, margin=margin)
