import gzip
from datetime import UTC, datetime
from pathlib import Path

import pytest

from eyewall.ndbc import historical
from eyewall.ndbc.historical import decompress, parse_historical, select_period
from eyewall.ndbc.stdmet import parse_stdmet

FIXTURES = Path(__file__).parent / "fixtures" / "ndbc"
SAMPLE = FIXTURES / "41025h2025_erin_week.txt.gz"


def test_gzipped_and_plain_text_give_the_same_series():
    packed = SAMPLE.read_bytes()
    text = gzip.decompress(packed)
    assert parse_historical(packed, "41025") == parse_historical(text, "41025")
    assert decompress(packed) == decompress(text) == text.decode()


def test_historical_rows_arrive_oldest_first_and_leave_newest_first():
    lines = gzip.decompress(SAMPLE.read_bytes()).decode().splitlines()
    data_times = [tuple(line.split()[:5]) for line in lines if not line.startswith("#")]
    assert data_times == sorted(data_times)  # the file really is oldest first
    series = parse_historical(SAMPLE.read_bytes(), "41025")
    assert series.observations[0].time > series.observations[-1].time


def test_select_period_is_inclusive_and_keeps_the_station():
    series = parse_historical(SAMPLE.read_bytes(), "41025")
    start, end = datetime(2025, 8, 20, 12, 0, tzinfo=UTC), datetime(2025, 8, 21, 12, 0, tzinfo=UTC)
    day = select_period(series, start, end)
    assert day.station_id == "41025"
    assert day.observations[-1].time == start
    assert day.observations[0].time == end
    assert len(day.observations) == 145  # 24 hours of 10-minute rows, both ends included
    assert select_period(series, end, start).observations == ()


def test_a_monthly_file_is_the_same_format_as_a_yearly_one():
    text = (
        "#YY  MM DD hh mm WDIR WSPD GST  WVHT   DPD   APD MWD   PRES  ATMP  WTMP  DEWP  VIS  TIDE\n"
        "#yr  mo dy hr mn degT m/s  m/s     m   sec   sec deg    hPa  degC  degC  degC  nmi    ft\n"
        "2026 09 01 00 00  89  5.8  6.9 99.00 99.00 99.00 999 1016.2  27.9  30.0  24.7 99.0 99.00\n"
        "2026 09 01 00 10  81  6.0  7.5  1.12  7.69  5.25  94 1016.1  27.9  30.0  24.8 99.0 99.00\n"
    )
    series = parse_historical(text.encode(), "41010")
    assert [o.wave_height_m for o in series.observations] == [1.12, None]
    assert series == parse_stdmet(text, "41010")


def test_oversized_decompressed_data_is_refused(monkeypatch):
    monkeypatch.setattr(historical, "MAX_UNCOMPRESSED_BYTES", 100)
    with pytest.raises(ValueError, match="larger than expected"):
        decompress(gzip.compress(b"x" * 500))
    assert decompress(gzip.compress(b"x" * 100)) == "x" * 100


def test_undecodable_bytes_are_replaced_not_fatal():
    assert decompress(b"abc\xff") == "abc�"
