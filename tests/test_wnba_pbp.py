import pandas as pd

from gametime.data.pbp import normalize_nbastats_pbp
from gametime.sports import WNBA


def test_wnba_ten_minute_quarters():
    raw = pd.DataFrame(
        {
            "GAME_ID": [1022400001, 1022400001],
            "EVENTNUM": [1, 2],
            "PERIOD": [1, 1],
            "PCTIMESTRING": ["10:00", "9:00"],
            "SCORE": ["0 - 0", "2 - 0"],
        }
    )
    out = normalize_nbastats_pbp(
        raw,
        period_length_sec=WNBA.period_length_sec,
        regulation_periods=WNBA.regulation_periods,
    )
    assert out.iloc[0]["sec_elapsed_game"] == 0.0
    assert out.iloc[1]["sec_elapsed_game"] == 60.0
    assert out.iloc[1]["sec_remaining_game"] == WNBA.regulation_seconds - 60.0
