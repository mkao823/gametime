from gametime.live.confidence import crunch_total_range


def test_crunch_range_only_in_crunch():
    assert crunch_total_range(220.0, 200.0, 0.90) is None
    r = crunch_total_range(220.0, 200.0, 0.95)
    assert r is not None
    assert r.low == 216.3
    assert r.high == 223.7


def test_crunch_range_floor_at_current_total():
    r = crunch_total_range(202.0, 210.0, 0.95, half_width=5.0)
    assert r is not None
    assert r.low == r.high == 207.0
