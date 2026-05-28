import pandas as pd

from gametime.features.pregame_join import add_pregame_features, attach_pregame_to_row


def test_add_pregame_features_fills_naive_vs_pregame():
    snapshots = pd.DataFrame(
        {
            "game_id": ["42400401", "42400401"],
            "naive_recent_total_final": [210.0, 215.0],
        }
    )
    lookup = pd.DataFrame(
        {
            "game_id": ["42400401"],
            "pregame_pred_total": [228.0],
            "pregame_pred_margin": [3.5],
            "elo_diff": [42.0],
            "pregame_margin_band_width": [28.0],
            "pregame_blowout_prob": [0.42],
        }
    )
    out = add_pregame_features(snapshots, lookup)
    assert list(out["pregame_pred_total"]) == [228.0, 228.0]
    assert list(out["naive_vs_pregame"]) == [-18.0, -13.0]


def test_attach_pregame_to_row():
    row = pd.Series({"naive_recent_total_final": 220.0, "pace_total": 2.1})
    out = attach_pregame_to_row(
        row,
        pregame_pred_total=230.0,
        pregame_pred_margin=-2.0,
        elo_diff=10.0,
        pregame_margin_band_width=30.0,
        pregame_blowout_prob=0.45,
    )
    assert out["pregame_pred_total"] == 230.0
    assert out["naive_vs_pregame"] == -10.0
    assert out["pregame_margin_band_width"] == 30.0
    assert out["pregame_blowout_prob"] == 0.45
