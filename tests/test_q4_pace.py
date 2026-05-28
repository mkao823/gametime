import pandas as pd

from gametime.pregame.q4_pace import q4_total_from_raw


def test_q4_total_classic_pbp():
    raw = pd.DataFrame(
        {
            "EVENTNUM": [1, 2, 3, 4, 5],
            "PERIOD": [3, 3, 4, 4, 4],
            "SCORE": ["50-48", "55-50", "55-50", "60-52", "58-55"],
        }
    )
    # Q3 ends 55+50=105; Q4 ends 58+55=113 -> q4_total=8
    assert q4_total_from_raw(raw) == 8.0


def test_q4_total_v3_pbp():
    raw = pd.DataFrame(
        {
            "actionNumber": [1, 2, 3, 4],
            "period": [3, 3, 4, 4],
            "scoreHome": [50.0, 55.0, 55.0, 58.0],
            "scoreAway": [48.0, 50.0, 52.0, 55.0],
        }
    )
    assert q4_total_from_raw(raw) == 8.0
