from datetime import datetime
from utils.time_utils import epoch_to_ist, ist_to_epoch

def test_epoch_roundtrip():
    value = datetime.fromisoformat("2026-10-22T10:00:00+05:30")
    assert abs(ist_to_epoch(value) - epoch_to_ist(ist_to_epoch(value)).timestamp()) < 1e-6

def test_naive_datetime_rejected():
    try:
        ist_to_epoch(datetime(2026, 1, 1))
    except ValueError:
        pass
    else:
        raise AssertionError("Naive datetime must be rejected")
