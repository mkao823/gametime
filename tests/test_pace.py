import pandas as pd

from gametime.features.pace import add_multi_window_pace, pace_first_quarter


def test_pace_first_quarter_freezes_after_q1():
    assert pace_first_quarter(50, 600, None) == 50 / 10 * 48
    assert pace_first_quarter(100, 900, 100) == 100 / 12 * 48


def test_add_multi_window_pace():
    rows = []
    for sec in range(0, 721, 60):
        rows.append({"game_id": "g1", "sec_elapsed_game": sec, "total_score": sec / 30})
    rows.append({"game_id": "g1", "sec_elapsed_game": 780, "total_score": 26.0})
    df = pd.DataFrame(rows)
    df["pace_total"] = df["total_score"] / (df["sec_elapsed_game"].clip(lower=30) / 60) * 48
    df["pace_recent"] = df["pace_total"]
    out = add_multi_window_pace(df, interval_seconds=60)
    assert "pace_10min" in out.columns
    assert "pace_1q" in out.columns
    assert "pace_vs_recent" in out.columns
    q1_end = out[out["sec_elapsed_game"] == 720].iloc[0]
    q2 = out[out["sec_elapsed_game"] == 780].iloc[0]
    assert q2["pace_1q"] == q1_end["total_score"] / 12 * 48
