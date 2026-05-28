from __future__ import annotations

import numpy as np
import pandas as pd

from gametime.data.pbp import REGULATION_PERIODS, PERIOD_LENGTH_SEC

REGULATION_SECONDS = REGULATION_PERIODS * PERIOD_LENGTH_SEC


def final_scores_by_game(events: pd.DataFrame) -> pd.DataFrame:
    idx = events.groupby("game_id")["event_num"].idxmax()
    finals = events.loc[idx, ["game_id", "home_score", "away_score"]].rename(
        columns={"home_score": "home_final", "away_score": "away_final"}
    )
    finals["total_final"] = finals["home_final"] + finals["away_final"]
    finals["margin_final"] = finals["home_final"] - finals["away_final"]
    return finals.reset_index(drop=True)


def build_snapshots(
    events: pd.DataFrame,
    interval_seconds: int = 60,
    regulation_seconds: int = REGULATION_SECONDS,
) -> pd.DataFrame:
    finals = final_scores_by_game(events)
    valid = events.dropna(subset=["sec_elapsed_game", "home_score", "away_score"])
    grid = np.arange(0, regulation_seconds + 1, interval_seconds)
    rows = []
    for game_id, g in valid.groupby("game_id", sort=False):
        g = g.sort_values("sec_elapsed_game")
        t = g["sec_elapsed_game"].to_numpy()
        snap = pd.DataFrame({"game_id": game_id, "sec_elapsed_game": grid})
        for col in ("sec_remaining_game", "home_score", "away_score", "total_score", "score_diff"):
            snap[col] = np.interp(grid, t, g[col].to_numpy(), left=np.nan, right=g[col].iloc[-1])
        snap["period"] = np.interp(
            grid, t, g["period"].to_numpy(), left=g["period"].iloc[0], right=g["period"].iloc[-1]
        )
        snap["period"] = snap["period"].round().clip(1, REGULATION_PERIODS).astype(int)
        rows.append(snap)
    snapshots = pd.concat(rows, ignore_index=True).dropna(subset=["home_score", "away_score"])
    snapshots = snapshots.merge(finals, on="game_id", how="inner")
    snapshots["pct_complete"] = snapshots["sec_elapsed_game"] / regulation_seconds
    snapshots["remaining_total"] = snapshots["total_final"] - snapshots["total_score"]
    snapshots["remaining_margin"] = snapshots["margin_final"] - snapshots["score_diff"]
    return snapshots
