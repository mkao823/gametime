from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from gametime.live.log import LivePredictionLogger


def _quarter_label(pct: float, period: float) -> str:
    if pct < 0.25:
        return "Q1"
    if pct < 0.5:
        return "Q2"
    if pct < 0.75:
        return "Q3"
    return "Q4+"


def _error_tier(abs_err: pd.Series) -> pd.Series:
    return pd.cut(
        abs_err,
        bins=[-0.001, 5, 10, 20, 999],
        labels=["matched_lte_5", "moderate_5_10", "off_10_20", "heavily_skewed_gt_20"],
    )


def prepare_game_timeline(
    preds: pd.DataFrame,
    outcome: pd.Series,
) -> pd.DataFrame:
    """Merge polls with final score and derived analysis columns."""
    actual_total = float(outcome["total_final"])
    home_final = float(outcome["home_final"])
    away_final = float(outcome["away_final"])

    df = preds.sort_values("recorded_at_utc").copy()
    df["actual_total"] = actual_total
    df["actual_home"] = home_final
    df["actual_away"] = away_final
    df["err_total"] = df["pred_total_final"] - actual_total
    df["abs_err"] = df["err_total"].abs()
    df["err_naive"] = df["naive_total_final"] - actual_total
    df["abs_err_naive"] = df["err_naive"].abs()
    df["pace"] = df.get("feat_pace_total", df.get("pace_total", np.nan))
    df["pace_recent"] = df.get("feat_pace_recent", np.nan)
    df["total_now"] = df.get("feat_total_score", np.nan)
    df["quarter"] = df.apply(
        lambda r: _quarter_label(float(r["pct_complete"]), float(r.get("feat_period", 0))),
        axis=1,
    )
    df["tier"] = _error_tier(df["abs_err"])
    return df


def summarize_game_timeline(df: pd.DataFrame, game_id: str) -> dict[str, Any]:
    actual = float(df["actual_total"].iloc[0])
    matchup = df.get("matchup", pd.Series([""])).iloc[0] if "matchup" in df.columns else ""

    tier_counts = df["tier"].value_counts().sort_index()
    by_quarter = (
        df.groupby("quarter", observed=True)
        .agg(
            n=("abs_err", "count"),
            mae=("abs_err", "mean"),
            bias=("err_total", "mean"),
            pred_mean=("pred_total_final", "mean"),
            pace_mean=("pace", "mean"),
            score_mean=("total_now", "mean"),
        )
        .round(2)
    )

    early = df[df["pct_complete"] < 0.35]
    late = df[df["pct_complete"] >= 0.75]

    def _snapshots(sub: pd.DataFrame, n: int, col: str, largest: bool) -> list[dict]:
        if sub.empty:
            return []
        ordered = sub.nlargest(n, col) if largest else sub.nsmallest(n, col)
        cols = [
            "recorded_at_utc",
            "quarter",
            "pct_complete",
            "total_now",
            "pred_total_final",
            "naive_total_final",
            "abs_err",
            "pace",
            "tier",
        ]
        cols = [c for c in cols if c in ordered.columns]
        return ordered[cols].round(2).to_dict(orient="records")

    within5 = df[df["abs_err"] <= 5]
    skewed = df[df["tier"] == "heavily_skewed_gt_20"]

    conclusions = []
    if len(early) and early["err_total"].mean() > 10:
        conclusions.append(
            "Early logged window over-predicted the final total; "
            "if scoring slowed after a hot stretch, treat early highs as pace/model overshoot rather than pure error."
        )
    if len(late) and late["abs_err"].mean() <= 8:
        conclusions.append(
            "Late-game predictions were close to the final total on average."
        )
    if len(within5) >= len(df) * 0.2:
        conclusions.append(
            f"Stable accuracy zone: {len(within5)} polls within 5 pts "
            f"(from {within5['pct_complete'].min():.0%} game complete)."
        )
    if len(skewed):
        conclusions.append(
            f"Heavily skewed (>20 pts) only in {skewed['quarter'].mode().iloc[0] if len(skewed) else '?'}"
            f" ({len(skewed)} polls); pred {skewed['pred_total_final'].min():.0f}"
            f"-{skewed['pred_total_final'].max():.0f} vs actual {actual:.0f}."
        )
    if df["err_total"].mean() > 3:
        conclusions.append(f"Model bias +{df['err_total'].mean():.1f} over the full logged game.")
    elif df["err_total"].mean() < -3:
        conclusions.append(f"Model bias {df['err_total'].mean():.1f} over the full logged game.")

    return {
        "status": "ok",
        "game_id": game_id,
        "matchup": str(matchup),
        "n_polls": len(df),
        "actual_total": actual,
        "actual_home": float(df["actual_home"].iloc[0]),
        "actual_away": float(df["actual_away"].iloc[0]),
        "mae_total": float(df["abs_err"].mean()),
        "bias_total": float(df["err_total"].mean()),
        "mae_naive": float(df["abs_err_naive"].mean()),
        "bias_naive": float(df["err_naive"].mean()),
        "tier_counts": {str(k): int(v) for k, v in tier_counts.items()},
        "by_quarter": by_quarter.reset_index().to_dict(orient="records"),
        "pace_early_mean": float(early["pace"].mean()) if len(early) else None,
        "pace_late_mean": float(late["pace"].mean()) if len(late) else None,
        "pred_early_mean": float(early["pred_total_final"].mean()) if len(early) else None,
        "pred_late_mean": float(late["pred_total_final"].mean()) if len(late) else None,
        "first_within_5_pts": _snapshots(within5.head(1), 1, "abs_err", False),
        "closest_to_final": _snapshots(df, 5, "abs_err", False),
        "most_over_predicted": _snapshots(df, 5, "err_total", True),
        "most_under_predicted": _snapshots(df, 5, "err_total", False),
        "heavily_skewed_window": _snapshots(skewed, 10, "abs_err", True) if len(skewed) else [],
        "conclusions": conclusions,
    }


def analyze_game(
    log_dir: str | Path,
    report_dir: str | Path,
    *,
    game_id: Optional[str] = None,
    matchup_home: Optional[str] = None,
    matchup_away: Optional[str] = None,
    model_type: Optional[str] = None,
) -> dict[str, Any]:
    """
    Per-game report: timeline CSV + summary JSON comparing preds to actual final.
    """
    log_dir, report_dir = Path(log_dir), Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    preds = LivePredictionLogger.load_predictions(log_dir)
    outcomes = LivePredictionLogger.load_outcomes(log_dir)
    if preds.empty:
        summary = {"status": "no_predictions", "hint": "Run gametime-live with logging enabled."}
        (report_dir / "summary.json").write_text(json.dumps(summary, indent=2))
        return summary
    if outcomes.empty:
        summary = {"status": "no_outcome", "hint": "Poll through final to log game_outcomes.parquet."}
        (report_dir / "summary.json").write_text(json.dumps(summary, indent=2))
        return summary

    if game_id:
        gid = str(game_id)
    elif matchup_home and matchup_away:
        home, away = matchup_home.upper(), matchup_away.upper()
        match = preds[
            ((preds["home_tricode"] == home) & (preds["away_tricode"] == away))
            | ((preds["home_tricode"] == away) & (preds["away_tricode"] == home))
        ]
        if match.empty:
            summary = {"status": "not_found", "matchup": f"{away} @ {home}"}
            (report_dir / "summary.json").write_text(json.dumps(summary, indent=2))
            return summary
        gid = match["game_id"].iloc[0]
    else:
        gids = preds["game_id"].unique()
        if len(gids) != 1:
            summary = {
                "status": "ambiguous",
                "game_ids": list(gids),
                "hint": "Pass --game-id or --home/--away",
            }
            (report_dir / "summary.json").write_text(json.dumps(summary, indent=2))
            return summary
        gid = str(gids[0])

    game_preds = preds[preds["game_id"] == gid]
    if model_type:
        game_preds = game_preds[game_preds["model_type"] == model_type]
        if game_preds.empty:
            available = sorted(preds.loc[preds["game_id"] == gid, "model_type"].unique())
            summary = {
                "status": "no_predictions",
                "game_id": gid,
                "model_type": model_type,
                "available_model_types": available,
            }
            (report_dir / f"{gid}_summary.json").write_text(json.dumps(summary, indent=2))
            return summary
    game_out = outcomes[outcomes["game_id"] == gid]
    if game_out.empty:
        summary = {"status": "no_outcome", "game_id": gid}
        (report_dir / f"{gid}_summary.json").write_text(json.dumps(summary, indent=2))
        return summary

    timeline = prepare_game_timeline(game_preds, game_out.iloc[0])
    summary = summarize_game_timeline(timeline, gid)
    summary["game_id"] = gid
    if model_type:
        summary["model_type"] = model_type

    stem = f"{gid}_{model_type}" if model_type else gid
    timeline.to_csv(report_dir / f"{stem}_timeline.csv", index=False)
    (report_dir / f"{stem}_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return summary
