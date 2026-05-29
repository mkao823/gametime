"""Head-to-head member: shrunk prior margin/total from last N regular-season meetings.

Hyperparameters (v1):
  - ``H2H_MEETING_WINDOW`` (N=10): max prior RS meetings between the two teams.
  - ``H2H_SHRINK_K`` (8): pseudo-count toward league prior; weight = n / (n + k).
    Margin shrinks toward 0; total shrinks toward ``2 * LEAGUE_RPG``.
  Sparse early-season or first meeting → league fallback (n=0).
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

from gametime.pregame.baseball.features import LEAGUE_RPG
from gametime.pregame.baseball.models.base import BaseballMemberModel
from gametime.pregame.baseball.prediction import MemberPrediction

# Last N regular-season meetings (any site) between the two teams.
H2H_MEETING_WINDOW = 10
# Empirical-Bayes pseudo-count toward league margin 0 / league total 2*LEAGUE_RPG.
H2H_SHRINK_K = 8.0
H2H_REGULAR_SEASON = "rg"

H2H_COLUMNS = [
    "h2h_n_meetings",
    "h2h_raw_margin",
    "h2h_raw_total",
    "h2h_shrink_margin",
    "h2h_shrink_total",
]


def _league_total() -> float:
    return 2.0 * LEAGUE_RPG


def _home_perspective_margin(row: object, focal_home: str) -> float:
    home_team = str(row.home_team)
    away_team = str(row.away_team)
    if home_team == focal_home:
        return float(row.home_runs) - float(row.away_runs)
    if away_team == focal_home:
        return float(row.away_runs) - float(row.home_runs)
    raise ValueError(f"Team {focal_home!r} not in matchup {home_team} vs {away_team}")


def _shrink_pair(
    raw_margin: float,
    raw_total: float,
    n: int,
    *,
    shrink_k: float,
) -> tuple[float, float]:
    league_total = _league_total()
    if n <= 0:
        return 0.0, league_total
    w = float(n) / (float(n) + shrink_k) if shrink_k > 0 else 1.0
    shrink_margin = w * raw_margin
    shrink_total = w * raw_total + (1.0 - w) * league_total
    return shrink_margin, shrink_total


def _compute_h2h_by_game(
    games: pd.DataFrame,
    *,
    window: int,
    shrink_k: float,
    seasontype: str = H2H_REGULAR_SEASON,
) -> pd.DataFrame:
    """Causal H2H features per game_id (prior RS meetings only)."""
    g = games.sort_values(["game_date", "game_id"]).reset_index(drop=True)
    history: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)

    rows: list[dict[str, float | str]] = []
    for row in g.itertuples(index=False):
        home = str(row.home_team)
        away = str(row.away_team)
        key = tuple(sorted([home, away]))
        prior = history[key][-window:]
        n = len(prior)
        if n == 0:
            raw_margin, raw_total = 0.0, _league_total()
        else:
            raw_margin = float(np.mean([p[0] for p in prior]))
            raw_total = float(np.mean([p[1] for p in prior]))
        shrink_margin, shrink_total = _shrink_pair(
            raw_margin, raw_total, n, shrink_k=shrink_k
        )
        rows.append(
            {
                "game_id": row.game_id,
                "h2h_n_meetings": float(n),
                "h2h_raw_margin": raw_margin,
                "h2h_raw_total": raw_total,
                "h2h_shrink_margin": shrink_margin,
                "h2h_shrink_total": shrink_total,
            }
        )
        if str(row.seasontype) == seasontype:
            margin_hp = _home_perspective_margin(row, home)
            total = float(row.home_runs) + float(row.away_runs)
            history[key].append((margin_hp, total))

    return pd.DataFrame(rows)


def attach_h2h(
    table: pd.DataFrame,
    games: pd.DataFrame,
    *,
    window: int = H2H_MEETING_WINDOW,
    shrink_k: float = H2H_SHRINK_K,
    seasontype: str = H2H_REGULAR_SEASON,
) -> pd.DataFrame:
    """Attach prior-only head-to-head margin/total (RS history) to the training table."""
    h2h = _compute_h2h_by_game(
        games, window=window, shrink_k=shrink_k, seasontype=seasontype
    ).set_index("game_id")
    out = table.copy()
    for col in H2H_COLUMNS:
        out[col] = out["game_id"].map(h2h[col])
        if col == "h2h_n_meetings":
            out[col] = out[col].fillna(0.0)
        elif col in ("h2h_raw_margin", "h2h_shrink_margin"):
            out[col] = out[col].fillna(0.0)
        else:
            out[col] = out[col].fillna(_league_total())
    return out


def latest_h2h_columns(
    games: pd.DataFrame,
    *,
    home: str,
    away: str,
    window: int = H2H_MEETING_WINDOW,
    shrink_k: float = H2H_SHRINK_K,
    seasontype: str = H2H_REGULAR_SEASON,
) -> dict[str, float]:
    """H2H features for the next matchup from all prior RS games in ``games``."""
    home, away = home.upper(), away.upper()
    rs = games[games["seasontype"].astype(str) == seasontype].sort_values(
        ["game_date", "game_id"]
    )
    margins: list[float] = []
    totals: list[float] = []
    for row in rs.itertuples(index=False):
        ht, at = str(row.home_team), str(row.away_team)
        if {ht, at} != {home, away}:
            continue
        margins.append(_home_perspective_margin(row, home))
        totals.append(float(row.home_runs) + float(row.away_runs))
    prior_m = margins[-window:]
    prior_t = totals[-window:]
    n = len(prior_m)
    if n == 0:
        raw_margin, raw_total = 0.0, _league_total()
    else:
        raw_margin = float(np.mean(prior_m))
        raw_total = float(np.mean(prior_t))
    shrink_margin, shrink_total = _shrink_pair(
        raw_margin, raw_total, n, shrink_k=shrink_k
    )
    return {
        "h2h_n_meetings": float(n),
        "h2h_raw_margin": raw_margin,
        "h2h_raw_total": raw_total,
        "h2h_shrink_margin": shrink_margin,
        "h2h_shrink_total": shrink_total,
    }


class H2HMember(BaseballMemberModel):
    """Shrunk head-to-head margin; total held near league mean (optional weak H2H total)."""

    name = "h2h"

    def __init__(
        self,
        *,
        league_total_fallback: float | None = None,
    ) -> None:
        self._league_total = (
            league_total_fallback if league_total_fallback is not None else _league_total()
        )
        self._margin_bias = 0.0
        self._total_bias = 0.0

    def fit(self, train_df: pd.DataFrame) -> None:
        raw_margin = train_df["h2h_shrink_margin"].to_numpy(dtype=float)
        raw_total = train_df["h2h_shrink_total"].to_numpy(dtype=float)
        self._margin_bias = float(train_df["margin_final"].mean() - np.mean(raw_margin))
        self._total_bias = float(train_df["total_final"].mean() - np.mean(raw_total))

    def predict(self, df: pd.DataFrame) -> MemberPrediction:
        margin = df["h2h_shrink_margin"].to_numpy(dtype=float) + self._margin_bias
        total = df["h2h_shrink_total"].to_numpy(dtype=float) + self._total_bias
        return MemberPrediction(member=self.name, total=total, margin=margin)
