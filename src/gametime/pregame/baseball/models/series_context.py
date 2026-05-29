"""Series context member (W6o): same-venue series index + prior-game / prior-series style.

Uses ``games.parquet`` only (no travel/rest duplication). Style proxies from final
linescores:
  - Blowout: ``|margin| >= BLOWOUT_MARGIN`` (default 5; tune on train).
  - Shutout: team runs_for == 0.
  - Walkoff approx: team was home, won, ``margin == 1`` (misses away walk-offs).
  - High-scoring: ``total_final >= HIGH_SCORING_TOTAL`` (default 12).

``is_series_finale`` is a causal proxy: ``series_game_num >= 4`` (no future schedule).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from gametime.pregame.baseball.features import LEAGUE_RPG
from gametime.pregame.baseball.models.base import BaseballMemberModel
from gametime.pregame.baseball.prediction import MemberPrediction

BLOWOUT_MARGIN = 5
HIGH_SCORING_TOTAL = 12
SERIES_FINALE_GAME_NUM = 4
SERIES_SHRINK_K = 8.0
SERIES_REGULAR_SEASON = "rg"
LEAGUE_TOTAL = 2.0 * LEAGUE_RPG

SERIES_CONTEXT_COLUMNS = [
    "series_game_num",
    "is_series_finale",
    "prior_game_home_win",
    "prior_game_total",
    "prior_game_margin",
    "last_series_games",
    "last_series_home_sweep",
    "last_series_away_sweep",
    "home_entering_blowout_win",
    "home_entering_blowout_loss",
    "home_entering_shutout",
    "home_entering_high_scoring",
    "home_entering_walkoff_win",
    "away_entering_blowout_win",
    "away_entering_blowout_loss",
    "away_entering_shutout",
    "away_entering_high_scoring",
    "away_entering_walkoff_win",
    "has_series_context",
]


@dataclass
class _TeamEnteringStyle:
    blowout_win: float = 0.0
    blowout_loss: float = 0.0
    shutout: float = 0.0
    high_scoring: float = 0.0
    walkoff_win: float = 0.0


@dataclass
class _CompletedSeries:
    n_games: int
    home_wins: int
    away_wins: int


@dataclass
class _MatchupSeriesState:
    series_num: int = 0
    last_date: Optional[pd.Timestamp] = None
    prior_home_win: float = 0.5
    prior_total: float = LEAGUE_TOTAL
    prior_margin: float = 0.0
    block_home_wins: int = 0
    block_away_wins: int = 0
    last_completed: Optional[_CompletedSeries] = None


def _shrink_binary(raw: float, n: int, *, shrink_k: float) -> float:
    if n <= 0:
        return 0.0
    w = float(n) / (float(n) + shrink_k) if shrink_k > 0 else 1.0
    return w * raw


def _shrink_count(raw: float, n: int, *, shrink_k: float, neutral: float) -> float:
    if n <= 0:
        return neutral
    w = float(n) / (float(n) + shrink_k) if shrink_k > 0 else 1.0
    return w * raw + (1.0 - w) * neutral


def _team_style_from_game(
    *,
    team: str,
    home_team: str,
    home_runs: float,
    away_runs: float,
    margin: float,
    total: float,
) -> _TeamEnteringStyle:
    is_home = team == home_team
    runs_for = home_runs if is_home else away_runs
    team_margin = margin if is_home else -margin
    won = team_margin > 0
    return _TeamEnteringStyle(
        blowout_win=float(won and team_margin >= BLOWOUT_MARGIN),
        blowout_loss=float((not won) and (-team_margin) >= BLOWOUT_MARGIN),
        shutout=float(runs_for <= 0),
        high_scoring=float(total >= HIGH_SCORING_TOTAL),
        walkoff_win=float(is_home and won and margin == 1),
    )


def _style_to_dict(prefix: str, style: _TeamEnteringStyle) -> dict[str, float]:
    return {
        f"{prefix}_entering_blowout_win": style.blowout_win,
        f"{prefix}_entering_blowout_loss": style.blowout_loss,
        f"{prefix}_entering_shutout": style.shutout,
        f"{prefix}_entering_high_scoring": style.high_scoring,
        f"{prefix}_entering_walkoff_win": style.walkoff_win,
    }


def _completed_series_features(
    completed: Optional[_CompletedSeries],
    *,
    shrink_k: float,
) -> tuple[float, float, float]:
    if completed is None or completed.n_games <= 0:
        return 3.0, 0.0, 0.0
    n = completed.n_games
    home_sweep = float(completed.home_wins == n and n >= 2)
    away_sweep = float(completed.away_wins == n and n >= 2)
    return (
        _shrink_count(float(n), n, shrink_k=shrink_k, neutral=3.0),
        _shrink_binary(home_sweep, n, shrink_k=shrink_k),
        _shrink_binary(away_sweep, n, shrink_k=shrink_k),
    )


def _finalize_series_block(state: _MatchupSeriesState) -> None:
    if state.series_num <= 0:
        return
    state.last_completed = _CompletedSeries(
        n_games=state.series_num,
        home_wins=state.block_home_wins,
        away_wins=state.block_away_wins,
    )


def _compute_series_context_by_game(
    games: pd.DataFrame,
    *,
    shrink_k: float = SERIES_SHRINK_K,
    seasontype: str = SERIES_REGULAR_SEASON,
) -> pd.DataFrame:
    g = games.sort_values(["game_date", "game_id"]).reset_index(drop=True)
    matchup_state: dict[tuple[str, str], _MatchupSeriesState] = {}
    team_style: dict[str, _TeamEnteringStyle] = {}
    rows: list[dict[str, float | str]] = []

    for row in g.itertuples(index=False):
        home = str(row.home_team)
        away = str(row.away_team)
        key = (home, away)
        game_date = pd.Timestamp(row.game_date).normalize()
        state = matchup_state.setdefault(key, _MatchupSeriesState())

        home_style = team_style.get(home, _TeamEnteringStyle())
        away_style = team_style.get(away, _TeamEnteringStyle())

        continues = (
            state.last_date is not None
            and (game_date - state.last_date).days == 1
        )
        if continues:
            series_num = state.series_num + 1
            prior_home_win = state.prior_home_win
            prior_total = state.prior_total
            prior_margin = state.prior_margin
        else:
            if state.series_num > 0:
                _finalize_series_block(state)
            series_num = 1
            prior_home_win = 0.5
            prior_total = LEAGUE_TOTAL
            prior_margin = 0.0

        last_games, last_home_sweep, last_away_sweep = _completed_series_features(
            state.last_completed, shrink_k=shrink_k
        )

        has_ctx = float(
            series_num >= 2
            or (state.last_completed is not None and state.last_completed.n_games > 0)
            or home in team_style
            or away in team_style
        )

        rows.append(
            {
                "game_id": row.game_id,
                "series_game_num": float(series_num),
                "is_series_finale": float(series_num >= SERIES_FINALE_GAME_NUM),
                "prior_game_home_win": float(prior_home_win),
                "prior_game_total": float(prior_total),
                "prior_game_margin": float(prior_margin),
                "last_series_games": float(last_games),
                "last_series_home_sweep": float(last_home_sweep),
                "last_series_away_sweep": float(last_away_sweep),
                "has_series_context": has_ctx,
                **_style_to_dict("home", home_style),
                **_style_to_dict("away", away_style),
            }
        )

        if str(row.seasontype) != seasontype:
            continue

        margin = float(row.margin_final)
        total = float(row.home_runs) + float(row.away_runs)
        home_win = 1.0 if margin > 0 else 0.0

        if continues:
            state.block_home_wins += int(home_win)
            state.block_away_wins += int(1 - home_win)
        else:
            state.block_home_wins = int(home_win)
            state.block_away_wins = int(1 - home_win)

        state.series_num = series_num
        state.last_date = game_date
        state.prior_home_win = home_win
        state.prior_total = total
        state.prior_margin = margin

        team_style[home] = _team_style_from_game(
            team=home,
            home_team=home,
            home_runs=float(row.home_runs),
            away_runs=float(row.away_runs),
            margin=margin,
            total=total,
        )
        team_style[away] = _team_style_from_game(
            team=away,
            home_team=home,
            home_runs=float(row.home_runs),
            away_runs=float(row.away_runs),
            margin=margin,
            total=total,
        )

    return pd.DataFrame(rows)


def attach_series_context(
    table: pd.DataFrame,
    games: pd.DataFrame,
    *,
    shrink_k: float = SERIES_SHRINK_K,
    seasontype: str = SERIES_REGULAR_SEASON,
) -> pd.DataFrame:
    """Attach causal series-context columns (prior games only)."""
    ctx = _compute_series_context_by_game(
        games, shrink_k=shrink_k, seasontype=seasontype
    ).set_index("game_id")
    out = table.copy()
    defaults: dict[str, float] = {
        "series_game_num": 1.0,
        "is_series_finale": 0.0,
        "prior_game_home_win": 0.5,
        "prior_game_total": LEAGUE_TOTAL,
        "prior_game_margin": 0.0,
        "last_series_games": 3.0,
        "last_series_home_sweep": 0.0,
        "last_series_away_sweep": 0.0,
        "has_series_context": 0.0,
    }
    for col in SERIES_CONTEXT_COLUMNS:
        default = defaults.get(col, 0.0)
        out[col] = out["game_id"].map(ctx[col]).fillna(default)
    return out


def latest_series_context_columns(
    games: pd.DataFrame,
    *,
    home: str,
    away: str,
    shrink_k: float = SERIES_SHRINK_K,
    seasontype: str = SERIES_REGULAR_SEASON,
) -> dict[str, float]:
    """Series-context features for the next matchup from prior RS games."""
    from gametime.pregame.baseball.features import _team_game_rows

    home, away = home.upper(), away.upper()
    defaults: dict[str, float] = {c: 0.0 for c in SERIES_CONTEXT_COLUMNS}
    defaults.update(
        {
            "series_game_num": 1.0,
            "prior_game_home_win": 0.5,
            "prior_game_total": LEAGUE_TOTAL,
            "last_series_games": 3.0,
        }
    )
    if games.empty or "seasontype" not in games.columns:
        return defaults
    rs = games[games["seasontype"].astype(str) == seasontype].sort_values(
        ["game_date", "game_id"]
    )
    if rs.empty:
        return defaults

    ctx = attach_series_context(
        rs[["game_id", "home_team", "away_team", "game_date"]].copy(),
        rs,
        shrink_k=shrink_k,
        seasontype=seasontype,
    )

    def _entering(team: str, prefix: str) -> None:
        tg = _team_game_rows(rs)
        sub = tg[tg["team"].astype(str).str.upper() == team]
        if sub.empty:
            return
        gid = sub.iloc[-1]["game_id"]
        g_row = rs.loc[rs["game_id"] == gid].iloc[-1]
        ht = str(g_row["home_team"])
        margin = float(g_row["margin_final"])
        total = float(g_row["home_runs"]) + float(g_row["away_runs"])
        style = _team_style_from_game(
            team=team,
            home_team=ht,
            home_runs=float(g_row["home_runs"]),
            away_runs=float(g_row["away_runs"]),
            margin=margin,
            total=total,
        )
        defaults.update(_style_to_dict(prefix, style))

    _entering(home, "home")
    _entering(away, "away")

    matchup = rs[
        (rs["home_team"].astype(str).str.upper() == home)
        & (rs["away_team"].astype(str).str.upper() == away)
    ]
    if matchup.empty:
        defaults["has_series_context"] = float(
            defaults.get("home_entering_blowout_win", 0) > 0
            or defaults.get("away_entering_blowout_win", 0) > 0
            or home in rs["home_team"].astype(str).str.upper().values
        )
        return defaults

    last = matchup.iloc[-1]
    last_row = ctx.loc[ctx["game_id"] == last["game_id"]].iloc[-1]
    last_date = pd.Timestamp(last["game_date"]).normalize()
    next_day = last_date + pd.Timedelta(days=1)
    # Consecutive-day series continuation (causal default for live inference).
    series_num = float(last_row["series_game_num"]) + 1.0

    out = {c: float(last_row[c]) for c in SERIES_CONTEXT_COLUMNS}
    out["series_game_num"] = series_num
    out["is_series_finale"] = float(series_num >= SERIES_FINALE_GAME_NUM)
    out["prior_game_home_win"] = float(1.0 if float(last["margin_final"]) > 0 else 0.0)
    out["prior_game_total"] = float(last["home_runs"]) + float(last["away_runs"])
    out["prior_game_margin"] = float(last["margin_final"])
    out["has_series_context"] = 1.0
    for col in SERIES_CONTEXT_COLUMNS:
        if "entering" in col:
            out[col] = defaults[col]
    _ = next_day
    return out


def _raw_predictions(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    series_num = pd.to_numeric(df["series_game_num"], errors="coerce").fillna(1.0).to_numpy()
    prior_total = (
        pd.to_numeric(df["prior_game_total"], errors="coerce").fillna(LEAGUE_TOTAL).to_numpy()
    )
    prior_margin = pd.to_numeric(df["prior_game_margin"], errors="coerce").fillna(0.0).to_numpy()
    last_games = pd.to_numeric(df["last_series_games"], errors="coerce").fillna(3.0).to_numpy()
    has_ctx = pd.to_numeric(df["has_series_context"], errors="coerce").fillna(0.0).to_numpy()

    home_bb = (
        pd.to_numeric(df["home_entering_blowout_loss"], errors="coerce").fillna(0.0).to_numpy()
        + pd.to_numeric(df["away_entering_blowout_loss"], errors="coerce").fillna(0.0).to_numpy()
    )
    high_scoring_enter = (
        pd.to_numeric(df["home_entering_high_scoring"], errors="coerce").fillna(0.0).to_numpy()
        + pd.to_numeric(df["away_entering_high_scoring"], errors="coerce").fillna(0.0).to_numpy()
    )

    raw_total = (
        LEAGUE_TOTAL
        + has_ctx * (-0.04 * np.maximum(0.0, series_num - 1.0))
        + has_ctx * 0.06 * (prior_total - LEAGUE_TOTAL)
        + has_ctx * 0.03 * (last_games - 3.0)
        + has_ctx * 0.12 * home_bb
        + has_ctx * 0.08 * high_scoring_enter
    )
    raw_margin = has_ctx * (0.08 * prior_margin)
    return raw_total, raw_margin


class SeriesContextMember(BaseballMemberModel):
    """Series index + bounce-back heuristics; primary target total."""

    name = "series_context"

    def __init__(self) -> None:
        self._total_bias = 0.0
        self._margin_bias = 0.0

    def fit(self, train_df: pd.DataFrame) -> None:
        raw_total, raw_margin = _raw_predictions(train_df)
        self._total_bias = float(train_df["total_final"].mean() - np.mean(raw_total))
        self._margin_bias = float(train_df["margin_final"].mean() - np.mean(raw_margin))

    def predict(self, df: pd.DataFrame) -> MemberPrediction:
        raw_total, raw_margin = _raw_predictions(df)
        return MemberPrediction(
            member=self.name,
            total=raw_total + self._total_bias,
            margin=raw_margin + self._margin_bias,
        )
