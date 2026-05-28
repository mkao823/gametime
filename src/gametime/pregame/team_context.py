"""Causal team-context features derived from team_games (no dates, no box scores).

All rolling stats use shift(1) so only games *before* the target game contribute.
"""
from __future__ import annotations

import pandas as pd

from gametime.pregame.q4_pace import LEAGUE_Q4_PACE48

LEAGUE_PPG = 113.0
DEFAULT_REST_DAYS = 3.0

# Features planned but needing extra data or a follow-up PR.
FEATURE_ROADMAP: dict[str, str] = {
    "home_stand_len": "Consecutive home games on current homestand",
    "road_trip_len": "Consecutive away games on current road trip",
    "blowout_rate": "Share of last N games with |margin| > 15",
    "close_game_rate": "Share of last N games with |margin| < 5",
    "q4_margin_form": "Q4 scoring margin from PBP period splits",
    "opponent_adj_off": "Points scored adjusted for opponent def_elo",
    "elimination_game": "PO series clinching game (needs series wins)",
    "travel_miles": "Needs city/arena coordinates",
    "vegas_total_feature": "Closing line as model input, not blend (Iteration 3)",
    "injury_availability": "Star minutes delta (Tier 3 player data)",
    "on_off_net": "Lineup on/off net rating (Tier 3)",
    "coach_change": "Binary flag for new coach season",
    "altitude": "DEN/UTA altitude adjustment",
}


def _pair_key(home: pd.Series, away: pd.Series) -> pd.Series:
    a = home.astype(str).str.upper()
    b = away.astype(str).str.upper()
    return a.where(a < b, b) + "|" + b.where(a < b, a)


def _shifted_rolling(s: pd.Series, window: int, fn: str = "mean") -> pd.Series:
    rolled = s.shift(1).rolling(window=window, min_periods=1)
    if fn == "mean":
        return rolled.mean()
    if fn == "std":
        return rolled.std().fillna(0.0)
    raise ValueError(fn)


def _win_streak(won: pd.Series) -> pd.Series:
    """Length of current win streak entering this game (0 if last game was loss)."""
    streak = []
    run = 0
    for w in won.shift(1).fillna(0).astype(int):
        run = run + 1 if w == 1 else 0
        streak.append(run)
    return pd.Series(streak, index=won.index, dtype=float)


def _game_id_gap(game_ids: pd.Series) -> pd.Series:
    """Integer gap between consecutive team game_ids (rest proxy without dates)."""
    numeric = game_ids.astype(str).str.lstrip("0").replace("", "0").astype("int64")
    return numeric.diff().fillna(999)


def _series_game_number(games: pd.DataFrame) -> pd.Series:
    """Playoff game index within a (season, matchup-pair) series; 0 for RS."""
    out = pd.Series(0, index=games.index, dtype=float)
    po = games[games["seasontype"] == "po"].copy()
    if po.empty:
        return out
    po = po.copy()
    po["pair"] = _pair_key(po["home_tricode"], po["away_tricode"])
    po = po.sort_values("game_id")
    po["series_game_n"] = po.groupby(["season_start_year", "pair"]).cumcount() + 1
    out.loc[po.index] = po["series_game_n"].astype(float)
    return out


def _po_games_before(games: pd.DataFrame, team_games: pd.DataFrame) -> pd.DataFrame:
    """PO games each team has already played this season before this game."""
    tg = team_games.sort_values(["team", "game_id"]).copy()
    tg["po_before"] = tg.groupby(["team", "season_start_year"])["seasontype"].transform(
        lambda s: (s == "po").shift(1).fillna(0).astype(int).cumsum()
    )
    home_po = tg.rename(columns={"team": "home_tricode", "po_before": "home_po_game_n"})[
        ["game_id", "home_tricode", "home_po_game_n"]
    ]
    away_po = tg.rename(columns={"team": "away_tricode", "po_before": "away_po_game_n"})[
        ["game_id", "away_tricode", "away_po_game_n"]
    ]
    return games.merge(home_po, on=["game_id", "home_tricode"], how="left").merge(
        away_po, on=["game_id", "away_tricode"], how="left"
    )


def _h2h_features(games: pd.DataFrame, team_games: pd.DataFrame, window: int = 3) -> pd.DataFrame:
    """Head-to-head avg total and margin from current home perspective (causal)."""
    tg = team_games.sort_values("game_id")
    league_total = 2.0 * LEAGUE_PPG
    totals, margins = [], []
    for row in games.itertuples(index=False):
        prior = tg[
            (tg["game_id"] < row.game_id)
            & (
                ((tg["team"] == row.home_tricode) & (tg["opponent"] == row.away_tricode))
                | ((tg["team"] == row.away_tricode) & (tg["opponent"] == row.home_tricode))
            )
        ].tail(window)
        if prior.empty:
            totals.append(league_total)
            margins.append(0.0)
            continue
        totals.append(float(prior["total"].mean()))
        home_margins = []
        for p in prior.itertuples(index=False):
            home_margins.append(float(p.margin) if p.team == row.home_tricode else -float(p.margin))
        margins.append(float(sum(home_margins) / len(home_margins)))
    out = games.copy()
    out["h2h_avg_total"] = totals
    out["h2h_home_margin"] = margins
    return out


def _rest_days_from_dates(dates: pd.Series) -> pd.Series:
    gap = dates.diff().dt.days
    return gap.sub(1).fillna(DEFAULT_REST_DAYS).clip(lower=0)


def _is_back_to_back_from_dates(dates: pd.Series) -> pd.Series:
    gap = dates.diff().dt.days
    return (gap == 1).fillna(False).astype(int)


def build_team_rolling_context(team_games: pd.DataFrame, window: int = 10) -> pd.DataFrame:
    """Per (game_id, team) rolling context; merge to game level in enrich_games."""
    tg = team_games.sort_values(["team", "game_id"]).reset_index(drop=True).copy()
    g = tg.groupby("team", sort=False)
    tg["form_off"] = g["points_for"].transform(lambda s: _shifted_rolling(s, window))
    tg["form_def"] = g["points_against"].transform(lambda s: _shifted_rolling(s, window))
    tg["form_total_std"] = g["total"].transform(lambda s: _shifted_rolling(s, window, "std"))
    tg["form_margin_std"] = g["margin"].transform(lambda s: _shifted_rolling(s, window, "std"))
    if "q4_pace48" in tg.columns:
        tg["form_q4_pace"] = g["q4_pace48"].transform(lambda s: _shifted_rolling(s, window))
    else:
        tg["form_q4_pace"] = LEAGUE_Q4_PACE48
    tg["win_streak"] = g["won"].transform(_win_streak)
    tg["rest_gap"] = g["game_id"].transform(_game_id_gap)
    if "game_date" in tg.columns and tg["game_date"].notna().any():
        tg["rest_days"] = g["game_date"].transform(_rest_days_from_dates)
        tg["is_back_to_back"] = g["game_date"].transform(_is_back_to_back_from_dates)
    else:
        tg["rest_days"] = DEFAULT_REST_DAYS
        tg["is_back_to_back"] = 0
    return tg[
        [
            "game_id",
            "team",
            "form_off",
            "form_def",
            "form_total_std",
            "form_margin_std",
            "form_q4_pace",
            "win_streak",
            "rest_gap",
            "rest_days",
            "is_back_to_back",
        ]
    ]


def enrich_games(
    games: pd.DataFrame,
    team_games: pd.DataFrame,
    *,
    window: int = 10,
) -> pd.DataFrame:
    """Attach home/away context columns to one-row-per-game dataframe."""
    ctx = build_team_rolling_context(team_games, window=window)
    home = ctx.rename(
        columns={
            "team": "home_tricode",
            "form_off": "home_form_off",
            "form_def": "home_form_def",
            "form_total_std": "home_form_total_std",
            "form_margin_std": "home_form_margin_std",
            "form_q4_pace": "home_form_q4_pace",
            "win_streak": "home_win_streak",
            "rest_gap": "home_rest_gap",
            "rest_days": "home_rest_days",
            "is_back_to_back": "home_is_back_to_back",
        }
    )
    away = ctx.rename(
        columns={
            "team": "away_tricode",
            "form_off": "away_form_off",
            "form_def": "away_form_def",
            "form_total_std": "away_form_total_std",
            "form_margin_std": "away_form_margin_std",
            "form_q4_pace": "away_form_q4_pace",
            "win_streak": "away_win_streak",
            "rest_gap": "away_rest_gap",
            "rest_days": "away_rest_days",
            "is_back_to_back": "away_is_back_to_back",
        }
    )
    df = games.merge(home, on=["game_id", "home_tricode"], how="left")
    df = df.merge(away, on=["game_id", "away_tricode"], how="left")
    df = _po_games_before(df, team_games)
    df = _h2h_features(df, team_games, window=3)
    df["series_game_n"] = _series_game_number(df)
    df["expected_form_total"] = df["home_form_off"] + df["away_form_off"]
    df["form_off_diff"] = df["home_form_off"] - df["away_form_off"]
    df["form_def_diff"] = df["home_form_def"] - df["away_form_def"]
    df["form_q4_pace_diff"] = df["home_form_q4_pace"] - df["away_form_q4_pace"]
    df["expected_q4_pace"] = (df["home_form_q4_pace"] + df["away_form_q4_pace"]) / 2.0
    defaults = {
        "home_form_off": LEAGUE_PPG,
        "away_form_off": LEAGUE_PPG,
        "home_form_def": LEAGUE_PPG,
        "away_form_def": LEAGUE_PPG,
        "form_off_diff": 0.0,
        "expected_form_total": 2.0 * LEAGUE_PPG,
        "home_form_total_std": 0.0,
        "away_form_total_std": 0.0,
        "home_form_margin_std": 0.0,
        "away_form_margin_std": 0.0,
        "home_form_q4_pace": LEAGUE_Q4_PACE48,
        "away_form_q4_pace": LEAGUE_Q4_PACE48,
        "form_q4_pace_diff": 0.0,
        "expected_q4_pace": LEAGUE_Q4_PACE48,
        "home_win_streak": 0.0,
        "away_win_streak": 0.0,
        "home_rest_gap": 999.0,
        "away_rest_gap": 999.0,
        "home_rest_days": DEFAULT_REST_DAYS,
        "away_rest_days": DEFAULT_REST_DAYS,
        "home_is_back_to_back": 0.0,
        "away_is_back_to_back": 0.0,
        "home_po_game_n": 0.0,
        "away_po_game_n": 0.0,
        "series_game_n": 0.0,
        "h2h_avg_total": 2.0 * LEAGUE_PPG,
        "h2h_home_margin": 0.0,
    }
    for col, val in defaults.items():
        if col in df.columns:
            df[col] = df[col].fillna(val)
    return df


def current_team_context(
    team_games: pd.DataFrame,
    team: str,
    *,
    window: int = 10,
) -> dict[str, float]:
    """Live inference: latest rolling context for one team."""
    rows = team_games[team_games["team"] == team].sort_values("game_id").tail(window)
    if rows.empty:
        return {
            "form_off": LEAGUE_PPG,
            "form_def": LEAGUE_PPG,
            "form_total_std": 0.0,
            "form_margin_std": 0.0,
            "form_q4_pace": LEAGUE_Q4_PACE48,
            "win_streak": 0.0,
            "rest_gap": 999.0,
            "rest_days": DEFAULT_REST_DAYS,
            "is_back_to_back": 0.0,
            "po_game_n": 0.0,
        }
    all_team = team_games[team_games["team"] == team].sort_values("game_id")
    po_n = float((all_team["seasontype"] == "po").sum())
    streak = 0
    for w in all_team["won"].iloc[::-1]:
        if int(w) == 1:
            streak += 1
        else:
            break
    gap = 999.0
    if len(all_team) >= 2:
        gids = all_team["game_id"].astype(str).str.lstrip("0").replace("", "0").astype("int64")
        gap = float(gids.iloc[-1] - gids.iloc[-2])
    rest_days = DEFAULT_REST_DAYS
    is_b2b = 0.0
    if "game_date" in all_team.columns and all_team["game_date"].notna().any():
        from datetime import date

        last_date = all_team["game_date"].dropna().iloc[-1]
        delta = (date.today() - last_date.date()).days
        rest_days = float(max(0, delta - 1))
        is_b2b = float(delta == 1)
    q4_pace = LEAGUE_Q4_PACE48
    if "q4_pace48" in rows.columns:
        q4_pace = float(rows["q4_pace48"].mean())
    return {
        "form_off": float(rows["points_for"].mean()),
        "form_def": float(rows["points_against"].mean()),
        "form_total_std": float(rows["total"].std(ddof=0)) if len(rows) > 1 else 0.0,
        "form_margin_std": float(rows["margin"].std(ddof=0)) if len(rows) > 1 else 0.0,
        "form_q4_pace": q4_pace,
        "win_streak": float(streak),
        "rest_gap": gap,
        "rest_days": rest_days,
        "is_back_to_back": is_b2b,
        "po_game_n": po_n,
    }


def current_h2h(
    team_games: pd.DataFrame,
    home: str,
    away: str,
    *,
    window: int = 3,
) -> tuple[float, float]:
    """Avg total and home-margin over last `window` meetings (any site)."""
    games = team_games[team_games["team"] == home].sort_values("game_id")
    meetings = games[games["opponent"] == away].tail(window)
    if meetings.empty:
        league_total = 2.0 * LEAGUE_PPG
        return league_total, 0.0
    totals = meetings["total"].astype(float)
    margins = meetings["margin"].astype(float)
    return float(totals.mean()), float(margins.mean())
