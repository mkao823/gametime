from __future__ import annotations

import pandas as pd

LATE_GAME_PCT = 0.875
CRUNCH_PCT = 0.9375
CLOSE_GAME_MARGIN = 8
BLOWOUT_MARGIN = 15


def assign_game_phase(pct_complete, score_diff, period=None) -> pd.Series:
    pct = pd.Series(pct_complete).astype(float)
    margin = pd.Series(score_diff).abs().astype(float)
    phase = pd.Series("mid", index=pct.index, dtype=object)
    phase[pct < 0.5] = "early"
    phase[(pct >= 0.5) & (pct < LATE_GAME_PCT)] = "mid"
    phase[(pct >= LATE_GAME_PCT) & (margin > CLOSE_GAME_MARGIN)] = "late"
    phase[(pct >= LATE_GAME_PCT) & (margin <= CLOSE_GAME_MARGIN)] = "late_close"
    phase[pct >= CRUNCH_PCT] = "crunch"
    if period is not None:
        per = pd.Series(period).astype(int)
        phase[(per >= 4) & (margin <= CLOSE_GAME_MARGIN) & (pct >= LATE_GAME_PCT)] = "late_close"
        phase[(per >= 4) & (pct >= CRUNCH_PCT)] = "crunch"
    return phase


def add_phase_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    margin = out["score_diff"].abs()
    pct = out["pct_complete"]
    out["game_phase"] = assign_game_phase(pct, out["score_diff"], out.get("period"))
    out["is_late_game"] = (pct >= LATE_GAME_PCT).astype(int)
    out["is_close"] = (margin <= CLOSE_GAME_MARGIN).astype(int)
    out["is_crunch"] = (pct >= CRUNCH_PCT).astype(int)
    out["is_blowout"] = (margin >= BLOWOUT_MARGIN).astype(int)
    out["late_close"] = ((out["is_late_game"] == 1) & (out["is_close"] == 1)).astype(int)
    return out
