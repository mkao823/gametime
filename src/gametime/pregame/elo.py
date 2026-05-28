"""538-style Elo for NBA team strength.

- Start each team at `base_rating` (1500).
- After each game: update by K * MOV_multiplier * (actual - expected).
- Home court adjustment is applied to the home team's rating when computing expectation.
- Between seasons, ratings regress `season_regression` of the way toward `base_rating`.

We walk team_games in game_id order. game_id ordering reflects schedule order
within each season (regular season game_id 002SSGGGGG increments by date; playoff
game_id 004SSRRGGG by round then game). For tie-breaking equal ids we keep input
order.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
from typing import Optional

import pandas as pd

DEFAULT_BASE = 1500.0
DEFAULT_K = 20.0
DEFAULT_HCA = 65.0
DEFAULT_SEASON_REGRESSION = 0.25


@dataclass
class EloParams:
    base_rating: float = DEFAULT_BASE
    k: float = DEFAULT_K
    home_court_adv: float = DEFAULT_HCA
    season_regression: float = DEFAULT_SEASON_REGRESSION


def _expected(home_rating: float, away_rating: float, hca: float) -> float:
    diff = (home_rating + hca) - away_rating
    return 1.0 / (1.0 + 10.0 ** (-diff / 400.0))


def _mov_multiplier(margin: float, rating_diff_with_hca: float) -> float:
    abs_margin = abs(margin)
    return ((abs_margin + 3.0) ** 0.8) / (7.5 + 0.006 * abs(rating_diff_with_hca))


@dataclass
class EloState:
    params: EloParams = field(default_factory=EloParams)
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
        home_pts: float,
        away_pts: float,
    ) -> tuple[float, float]:
        """Apply a finished game; return (home_pre, away_pre) ratings."""
        self._begin_season(home, season)
        self._begin_season(away, season)
        home_pre = self.rating(home)
        away_pre = self.rating(away)
        exp_home = _expected(home_pre, away_pre, self.params.home_court_adv)
        actual_home = 1.0 if home_pts > away_pts else 0.0 if home_pts < away_pts else 0.5
        margin = home_pts - away_pts
        rating_diff = (home_pre + self.params.home_court_adv) - away_pre
        if home_pts < away_pts:
            rating_diff = -rating_diff
        mov = _mov_multiplier(margin, rating_diff)
        delta = self.params.k * mov * (actual_home - exp_home)
        self.ratings[home] = home_pre + delta
        self.ratings[away] = away_pre - delta
        return home_pre, away_pre

    def to_dict(self) -> dict:
        return {
            "params": self.params.__dict__,
            "ratings": dict(self.ratings),
            "last_season": dict(self.last_season),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EloState":
        params = EloParams(**data.get("params", {}))
        state = cls(params=params)
        state.ratings = dict(data.get("ratings", {}))
        state.last_season = {k: int(v) for k, v in data.get("last_season", {}).items()}
        return state


def fit_elo(team_games: pd.DataFrame, params: Optional[EloParams] = None) -> tuple[pd.DataFrame, EloState]:
    """Walk team_games causally; return (per-game pre-game ratings DF, final state).

    The returned DataFrame has one row per game with columns:
    game_id, season_start_year, seasontype, home_tricode, away_tricode,
    home_final, away_final, home_elo_pre, away_elo_pre.
    """
    from gametime.pregame.team_games import to_game_level

    state = EloState(params=params or EloParams())
    games = to_game_level(team_games)
    games = games.sort_values("game_id").reset_index(drop=True)

    home_elo, away_elo = [], []
    for row in games.itertuples(index=False):
        h_pre, a_pre = state.update(
            season=int(row.season_start_year),
            home=row.home_tricode,
            away=row.away_tricode,
            home_pts=float(row.home_final),
            away_pts=float(row.away_final),
        )
        home_elo.append(h_pre)
        away_elo.append(a_pre)

    games["home_elo_pre"] = home_elo
    games["away_elo_pre"] = away_elo
    return games, state


def save_state(state: EloState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2))


def load_state(path: Path) -> EloState:
    return EloState.from_dict(json.loads(path.read_text()))


LEAGUE_PPG = 113.0
OFFDEF_SCALE = 38.0
OFFDEF_K = 0.35
OFFDEF_HCA_PTS = 2.5


@dataclass
class OffDefState:
    """Separate offensive / defensive strength (points for / against vs league avg)."""

    params: EloParams = field(default_factory=EloParams)
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

    def expected_home_pts(self, home: str, away: str) -> float:
        h = self.off_rating(home)
        a = self.def_rating(away)
        return (
            LEAGUE_PPG
            + (h - self.params.base_rating) / OFFDEF_SCALE
            - (a - self.params.base_rating) / OFFDEF_SCALE
            + OFFDEF_HCA_PTS
        )

    def expected_away_pts(self, home: str, away: str) -> float:
        a = self.off_rating(away)
        h = self.def_rating(home)
        return (
            LEAGUE_PPG
            + (a - self.params.base_rating) / OFFDEF_SCALE
            - (h - self.params.base_rating) / OFFDEF_SCALE
        )

    def update_game(
        self,
        *,
        season: int,
        home: str,
        away: str,
        home_pts: float,
        away_pts: float,
    ) -> tuple[float, float, float, float]:
        for team in (home, away):
            self._regress_season(team, season)
        h_off_pre = self.off_rating(home)
        a_off_pre = self.off_rating(away)
        h_def_pre = self.def_rating(home)
        a_def_pre = self.def_rating(away)
        exp_h = self.expected_home_pts(home, away)
        exp_a = self.expected_away_pts(home, away)
        self.off_ratings[home] = h_off_pre + OFFDEF_K * (home_pts - exp_h)
        self.def_ratings[away] = a_def_pre - OFFDEF_K * (home_pts - exp_h)
        self.off_ratings[away] = a_off_pre + OFFDEF_K * (away_pts - exp_a)
        self.def_ratings[home] = h_def_pre - OFFDEF_K * (away_pts - exp_a)
        return h_off_pre, a_off_pre, h_def_pre, a_def_pre

    def to_dict(self) -> dict:
        return {
            "params": self.params.__dict__,
            "off_ratings": dict(self.off_ratings),
            "def_ratings": dict(self.def_ratings),
            "last_season": dict(self.last_season),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "OffDefState":
        params = EloParams(**data.get("params", {}))
        state = cls(params=params)
        state.off_ratings = dict(data.get("off_ratings", {}))
        state.def_ratings = dict(data.get("def_ratings", {}))
        state.last_season = {k: int(v) for k, v in data.get("last_season", {}).items()}
        return state


def fit_off_def_elo(
    team_games: pd.DataFrame,
    params: Optional[EloParams] = None,
) -> tuple[pd.DataFrame, OffDefState]:
    from gametime.pregame.team_games import to_game_level

    state = OffDefState(params=params or EloParams())
    games = to_game_level(team_games).sort_values("game_id").reset_index(drop=True)
    h_off, a_off, h_def, a_def = [], [], [], []
    for row in games.itertuples(index=False):
        ho, ao, hd, ad = state.update_game(
            season=int(row.season_start_year),
            home=row.home_tricode,
            away=row.away_tricode,
            home_pts=float(row.home_final),
            away_pts=float(row.away_final),
        )
        h_off.append(ho)
        a_off.append(ao)
        h_def.append(hd)
        a_def.append(ad)
    games["home_off_elo_pre"] = h_off
    games["away_off_elo_pre"] = a_off
    games["home_def_elo_pre"] = h_def
    games["away_def_elo_pre"] = a_def
    return games, state


def save_offdef_state(state: OffDefState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2))


def load_offdef_state(path: Path) -> OffDefState:
    return OffDefState.from_dict(json.loads(path.read_text()))

