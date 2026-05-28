from __future__ import annotations

import pandas as pd

from gametime.live.fetch import LiveGameSnapshot
from gametime.live.inference import LivePrediction


def naive_prediction(snap: LiveGameSnapshot, row: pd.Series) -> LivePrediction:
    total_final = float(row["naive_recent_total_final"])
    margin = float(row["score_diff"])
    return LivePrediction(
        game_id=snap.game_id,
        matchup=f"{snap.away_tricode} @ {snap.home_tricode}",
        period=snap.period,
        clock=snap.clock_raw,
        home_score=snap.home_score,
        away_score=snap.away_score,
        status_text=snap.status_text,
        pred_total_final=total_final,
        pred_home_final=(total_final + margin) / 2,
        pred_away_final=(total_final - margin) / 2,
        naive_total_final=total_final,
        pct_complete=float(row["pct_complete"]),
        pace_total=float(row["pace_total"]),
        pace_recent=float(row["pace_recent"]),
    )
