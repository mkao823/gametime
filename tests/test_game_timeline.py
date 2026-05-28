import pandas as pd

from gametime.evaluate.game_timeline import prepare_game_timeline, summarize_game_timeline


def test_game_timeline_summary():
    preds = pd.DataFrame(
        {
            "game_id": ["g1"] * 4,
            "recorded_at_utc": ["a", "b", "c", "d"],
            "matchup": ["A @ B"] * 4,
            "pct_complete": [0.3, 0.5, 0.8, 0.9],
            "feat_period": [2, 2, 4, 4],
            "feat_total_score": [60, 90, 150, 160],
            "feat_pace_total": [200, 195, 185, 184],
            "feat_pace_recent": [200, 195, 185, 184],
            "pred_total_final": [210, 200, 186, 185],
            "naive_total_final": [205, 198, 187, 185],
        }
    )
    outcome = pd.Series({"total_final": 185, "home_final": 100, "away_final": 85})
    timeline = prepare_game_timeline(preds, outcome)
    assert "tier" in timeline.columns
    summary = summarize_game_timeline(timeline, "g1")
    assert summary["status"] == "ok"
    assert summary["actual_total"] == 185
    assert summary["n_polls"] == 4
