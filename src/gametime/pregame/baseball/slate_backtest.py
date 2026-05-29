"""Retro pregame slate backtest: honest daily accuracy without same-day leakage."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

from gametime.ingest.mlb import slate_from_games_parquet
from gametime.pregame.baseball.predict import BaseballPregamePredictor


def _normalize_game_dates(games: pd.DataFrame) -> pd.DataFrame:
    g = games.copy()
    g["game_date"] = pd.to_datetime(g["game_date"]).dt.normalize()
    return g


def discover_slate_dates(
    games: pd.DataFrame,
    *,
    end_date: date,
    days: int,
    regular_season_only: bool = True,
) -> list[date]:
    """Calendar dates in (end_date - days, end_date] with ≥1 completed RS game."""
    if games.empty or days <= 0:
        return []
    g = _normalize_game_dates(games)
    if regular_season_only and "seasontype" in g.columns:
        g = g[g["seasontype"] == "rg"]
    start = end_date - timedelta(days=days)
    day_series = g["game_date"].dt.date
    mask = (day_series > start) & (day_series <= end_date)
    if not mask.any():
        return []
    return sorted(day_series.loc[mask].unique())


def filter_pitcher_games_for_history(
    pitcher_games: Optional[pd.DataFrame],
    games_through: pd.DataFrame,
) -> Optional[pd.DataFrame]:
    """Drop sidecar rows whose ``game_id`` is absent from truncated games (no NaT dates)."""
    if pitcher_games is None or pitcher_games.empty:
        return pitcher_games
    ids = set(games_through["game_id"].astype(str))
    pg = pitcher_games[pitcher_games["game_id"].astype(str).isin(ids)].copy()
    return pg


def filter_weather_games_for_history(
    weather_games: Optional[pd.DataFrame],
    games_through: pd.DataFrame,
) -> Optional[pd.DataFrame]:
    if weather_games is None or weather_games.empty:
        return weather_games
    ids = set(games_through["game_id"].astype(str))
    return weather_games[weather_games["game_id"].astype(str).isin(ids)].copy()


def filter_lineup_games_for_history(
    lineup_games: Optional[pd.DataFrame],
    games_through: pd.DataFrame,
) -> Optional[pd.DataFrame]:
    if lineup_games is None or lineup_games.empty:
        return lineup_games
    ids = set(games_through["game_id"].astype(str))
    return lineup_games[lineup_games["game_id"].astype(str).isin(ids)].copy()


def write_games_through(
    games: pd.DataFrame,
    slate_date: date,
    out_path: Path,
) -> Path:
    """Persist games with ``game_date < slate_date`` (no same-day leakage)."""
    g = _normalize_game_dates(games)
    prior = g[g["game_date"].dt.date < slate_date]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prior.to_parquet(out_path, index=False)
    return out_path


def slate_actuals_for_date(
    games: pd.DataFrame,
    slate_date: date,
    *,
    regular_season_only: bool = True,
) -> pd.DataFrame:
    """Completed games on ``slate_date`` with actual totals/margins/winners."""
    g = _normalize_game_dates(games)
    td = pd.Timestamp(slate_date).normalize()
    sub = g[g["game_date"] == td]
    if regular_season_only and "seasontype" in sub.columns:
        sub = sub[sub["seasontype"] == "rg"]
    if sub.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, row in sub.iterrows():
        gid = str(row["game_id"])
        if gid in seen:
            continue
        seen.add(gid)
        home = str(row["home_team"])
        away = str(row["away_team"])
        hr = float(row["home_runs"])
        ar = float(row["away_runs"])
        margin = float(row["margin_final"]) if "margin_final" in row.index else hr - ar
        total = float(row["total_final"]) if "total_final" in row.index else hr + ar
        actual_winner = home if margin >= 0 else away
        rows.append(
            {
                "slate_date": slate_date.isoformat(),
                "game_id": gid,
                "matchup": f"{away} @ {home}",
                "home_team": home,
                "away_team": away,
                "actual_total": total,
                "actual_margin": margin,
                "actual_winner": actual_winner,
            }
        )
    return pd.DataFrame(rows)


def _winner_ok(pred_winner: str, actual_winner: str) -> bool:
    return pred_winner.upper() == actual_winner.upper()


def aggregate_daily_metrics(
    game_rows: pd.DataFrame,
    *,
    slate_date: date,
    blend_mode: str,
) -> dict[str, Any]:
    if game_rows.empty:
        return {}
    n = len(game_rows)
    return {
        "slate_date": slate_date.isoformat(),
        "n_games": n,
        "total_mae": float(game_rows["total_err"].abs().mean()),
        "margin_mae": float(game_rows["margin_err"].abs().mean()),
        "winner_accuracy": float(game_rows["winner_ok"].mean()),
        "bias_total": float(game_rows["total_err"].mean()),
        "blend_mode": blend_mode,
    }


def run_slate_backtest_day(
    games: pd.DataFrame,
    slate_date: date,
    *,
    model_dir: Path,
    games_through_dir: Path,
    form_window: int,
    runs_strength_window: int,
    train_seasons: list[int],
    train_seasontypes: list[str],
    use_stacking: bool,
    elo_params: Any,
    pitcher_games_path: Optional[Path],
    park_factors_path: Optional[Path],
    weather_games_path: Optional[Path] = None,
    lineup_games_path: Optional[Path] = None,
    league_total_fallback: float,
    h2h_window: int,
    h2h_shrink_k: float,
    regular_season_only: bool = True,
    is_playoff: bool = False,
    predictor_factory: Optional[Callable[..., BaseballPregamePredictor]] = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Score one slate date; history excludes games on or after ``slate_date``."""
    actuals = slate_actuals_for_date(
        games, slate_date, regular_season_only=regular_season_only
    )
    if actuals.empty:
        return pd.DataFrame(), {}

    through_path = games_through_dir / f"games_through_{slate_date.isoformat()}.parquet"
    games_through = _normalize_game_dates(games)
    games_through = games_through[games_through["game_date"].dt.date < slate_date]
    write_games_through(games, slate_date, through_path)

    pitcher_path = pitcher_games_path
    if pitcher_games_path is not None and Path(pitcher_games_path).exists():
        pg_full = pd.read_parquet(pitcher_games_path)
        pg_filtered = filter_pitcher_games_for_history(pg_full, games_through)
        if pg_filtered is not None and len(pg_filtered) < len(pg_full):
            pitcher_through = (
                games_through_dir / f"pitcher_games_through_{slate_date.isoformat()}.parquet"
            )
            pg_filtered.to_parquet(pitcher_through, index=False)
            pitcher_path = pitcher_through
    weather_path = weather_games_path
    if weather_games_path is not None and Path(weather_games_path).exists():
        wg_full = pd.read_parquet(weather_games_path)
        wg_filtered = filter_weather_games_for_history(wg_full, games_through)
        if wg_filtered is not None and len(wg_filtered) < len(wg_full):
            weather_through = (
                games_through_dir / f"weather_games_through_{slate_date.isoformat()}.parquet"
            )
            wg_filtered.to_parquet(weather_through, index=False)
            weather_path = weather_through
    lineup_path = lineup_games_path
    if lineup_games_path is not None and Path(lineup_games_path).exists():
        lg_full = pd.read_parquet(lineup_games_path)
        lg_filtered = filter_lineup_games_for_history(lg_full, games_through)
        if lg_filtered is not None and len(lg_filtered) < len(lg_full):
            lineup_through = (
                games_through_dir / f"lineup_games_through_{slate_date.isoformat()}.parquet"
            )
            lg_filtered.to_parquet(lineup_through, index=False)
            lineup_path = lineup_through

    factory = predictor_factory or BaseballPregamePredictor
    predictor = factory(
        model_dir,
        through_path,
        form_window=form_window,
        runs_strength_window=runs_strength_window,
        train_seasons=train_seasons,
        train_seasontypes=train_seasontypes,
        use_stacking=use_stacking,
        elo_params=elo_params,
        pitcher_games_path=pitcher_path,
        park_factors_path=park_factors_path,
        weather_games_path=weather_path,
        lineup_games_path=lineup_path,
        league_total_fallback=league_total_fallback,
        h2h_window=h2h_window,
        h2h_shrink_k=h2h_shrink_k,
    )

    blend_mode = "stacking" if use_stacking else "linear"
    n_day = len(actuals)
    scored: list[dict[str, Any]] = []
    for _, act in actuals.iterrows():
        home = act["home_team"]
        away = act["away_team"]
        try:
            pred = predictor.predict(home=home, away=away, is_playoff=is_playoff)
        except Exception as exc:
            scored.append(
                {
                    "slate_date": slate_date.isoformat(),
                    "game_id": act["game_id"],
                    "matchup": act["matchup"],
                    "home_team": home,
                    "away_team": away,
                    "error": str(exc),
                    "n_games_that_day": n_day,
                }
            )
            continue
        total_err = float(pred.pred_total) - float(act["actual_total"])
        margin_err = float(pred.pred_margin) - float(act["actual_margin"])
        scored.append(
            {
                "slate_date": slate_date.isoformat(),
                "game_id": act["game_id"],
                "matchup": act["matchup"],
                "home_team": home,
                "away_team": away,
                "pred_total": float(pred.pred_total),
                "pred_margin": float(pred.pred_margin),
                "pred_winner": pred.winner_tricode,
                "actual_total": float(act["actual_total"]),
                "actual_margin": float(act["actual_margin"]),
                "actual_winner": act["actual_winner"],
                "total_err": total_err,
                "margin_err": margin_err,
                "winner_ok": _winner_ok(pred.winner_tricode, act["actual_winner"]),
                "n_games_that_day": n_day,
                "blend_mode": blend_mode,
            }
        )

    game_df = pd.DataFrame(scored)
    if len(game_df) and "pred_total" in game_df.columns:
        ok = game_df[game_df["pred_total"].notna()]
    else:
        ok = pd.DataFrame()
    daily = aggregate_daily_metrics(
        ok, slate_date=slate_date, blend_mode=blend_mode
    )
    return game_df, daily


def run_slate_backtest(
    games: pd.DataFrame,
    slate_dates: list[date],
    *,
    model_dir: Path,
    games_through_dir: Path,
    form_window: int,
    runs_strength_window: int,
    train_seasons: list[int],
    train_seasontypes: list[str],
    use_stacking: bool,
    elo_params: Any,
    pitcher_games_path: Optional[Path],
    park_factors_path: Optional[Path],
    weather_games_path: Optional[Path] = None,
    lineup_games_path: Optional[Path] = None,
    league_total_fallback: float,
    h2h_window: int,
    h2h_shrink_k: float,
    regular_season_only: bool = True,
    is_playoff: bool = False,
    predictor_factory: Optional[Callable[..., BaseballPregamePredictor]] = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run backtest for each slate date; skip empty slates."""
    daily_rows: list[dict[str, Any]] = []
    game_frames: list[pd.DataFrame] = []
    for sd in slate_dates:
        game_df, daily = run_slate_backtest_day(
            games,
            sd,
            model_dir=model_dir,
            games_through_dir=games_through_dir,
            form_window=form_window,
            runs_strength_window=runs_strength_window,
            train_seasons=train_seasons,
            train_seasontypes=train_seasontypes,
            use_stacking=use_stacking,
            elo_params=elo_params,
            pitcher_games_path=pitcher_games_path,
            park_factors_path=park_factors_path,
            weather_games_path=weather_games_path,
            lineup_games_path=lineup_games_path,
            league_total_fallback=league_total_fallback,
            h2h_window=h2h_window,
            h2h_shrink_k=h2h_shrink_k,
            regular_season_only=regular_season_only,
            is_playoff=is_playoff,
            predictor_factory=predictor_factory,
        )
        if daily:
            daily_rows.append(daily)
        if len(game_df):
            game_frames.append(game_df)

    daily_df = pd.DataFrame(daily_rows)
    games_df = pd.concat(game_frames, ignore_index=True) if game_frames else pd.DataFrame()
    return daily_df, games_df


def default_end_date(games: pd.DataFrame) -> date:
    """Yesterday (local) or latest completed game date in parquet, whichever is earlier."""
    yesterday = date.today() - timedelta(days=1)
    if games.empty:
        return yesterday
    g = _normalize_game_dates(games)
    max_d = g["game_date"].max().date()
    return min(max_d, yesterday)


def write_backtest_outputs(
    daily_df: pd.DataFrame,
    games_df: pd.DataFrame,
    out_dir: Path,
    *,
    append: bool = False,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "daily_parquet": out_dir / "slate_backtest_daily.parquet",
        "daily_json": out_dir / "slate_backtest_daily.json",
        "games_parquet": out_dir / "slate_backtest_games.parquet",
    }

    if append and paths["daily_parquet"].exists() and len(daily_df):
        existing_daily = pd.read_parquet(paths["daily_parquet"])
        existing_dates = set(existing_daily["slate_date"].astype(str))
        daily_df = daily_df[~daily_df["slate_date"].astype(str).isin(existing_dates)]
        if len(daily_df):
            daily_df = pd.concat([existing_daily, daily_df], ignore_index=True)
        else:
            daily_df = existing_daily

    if append and paths["games_parquet"].exists() and len(games_df):
        existing_games = pd.read_parquet(paths["games_parquet"])
        existing_keys = set(
            zip(
                existing_games["slate_date"].astype(str),
                existing_games["game_id"].astype(str),
            )
        )
        mask = ~games_df.apply(
            lambda r: (str(r["slate_date"]), str(r["game_id"])) in existing_keys,
            axis=1,
        )
        new_games = games_df.loc[mask]
        if len(new_games):
            games_df = pd.concat([existing_games, new_games], ignore_index=True)
        else:
            games_df = existing_games

    if len(daily_df):
        daily_df.to_parquet(paths["daily_parquet"], index=False)
        summary = {
            "n_slate_dates": int(len(daily_df)),
            "date_range": {
                "min": str(daily_df["slate_date"].min()),
                "max": str(daily_df["slate_date"].max()),
            },
            "total_games_scored": int(daily_df["n_games"].sum()),
            "blend_mode": str(daily_df["blend_mode"].iloc[0])
            if "blend_mode" in daily_df.columns
            else None,
            "daily": daily_df.to_dict(orient="records"),
        }
        with paths["daily_json"].open("w") as f:
            json.dump(summary, f, indent=2)
    if len(games_df):
        games_df.to_parquet(paths["games_parquet"], index=False)

    return paths


def slate_dates_from_parquet(
    games: pd.DataFrame,
    target_date: date,
    *,
    regular_season_only: bool = True,
) -> list[dict[str, str]]:
    """Thin wrapper for tests — same matchups as production slate discovery."""
    return slate_from_games_parquet(
        games, target_date, regular_season_only=regular_season_only
    )
