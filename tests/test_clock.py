from datetime import UTC, datetime, timedelta, timezone

import pytest

from eyewall.clock import SystemClock, VirtualClock, ensure_utc, format_age, format_zulu, parse_utc

START = datetime(2026, 9, 25, 6, 0, tzinfo=UTC)


def test_virtual_clock_advances_both_readings():
    clock = VirtualClock(START)
    clock.advance(90)
    assert clock.now() == START + timedelta(seconds=90)
    assert clock.monotonic() == 90


def test_virtual_clock_set_can_go_backwards_but_monotonic_cannot():
    clock = VirtualClock(START)
    clock.advance(60)
    clock.set(START - timedelta(hours=6))
    assert clock.now() == START - timedelta(hours=6)
    assert clock.monotonic() == 60


def test_virtual_clock_rejects_negative_advance_and_naive_times():
    clock = VirtualClock(START)
    with pytest.raises(ValueError):
        clock.advance(-1)
    with pytest.raises(ValueError):
        clock.set(datetime(2026, 9, 25, 6, 0))
    with pytest.raises(ValueError):
        VirtualClock(datetime(2026, 9, 25))


def test_system_clock_is_utc_and_monotonic():
    clock = SystemClock()
    assert clock.now().utcoffset() == timedelta(0)
    first = clock.monotonic()
    assert clock.monotonic() >= first


def test_ensure_utc_converts_other_zones():
    eastern = timezone(timedelta(hours=-4))
    assert ensure_utc(datetime(2026, 9, 25, 2, 0, tzinfo=eastern)) == START


def test_parse_utc():
    assert parse_utc("2026-09-25T06:00:00.000Z") == START
    assert parse_utc("2026-09-25T06:00:00") == START
    assert parse_utc("2026-09-25T02:00:00-04:00") == START


def test_format_age():
    assert format_age(None) == "--"
    assert format_age(-5) == "0s"
    assert format_age(12) == "12s"
    assert format_age(185) == "3m05s"
    assert format_age(7620) == "2h07m"


def test_format_zulu():
    assert format_zulu(START) == "06:00Z"
    assert format_zulu(START, day=True) == "Fri 06:00Z"


def test_format_when():
    from eyewall.clock import format_when

    moment = datetime(2025, 8, 20, 21, 0, tzinfo=UTC)
    edt = timezone(timedelta(hours=-4), "EDT")
    assert format_when(moment) == "21:00Z"
    assert format_when(moment, edt) == "21:00Z (17:00 EDT)"
    assert format_when(moment, edt, day=True) == "Wed 21:00Z (Wed 17:00 EDT)"
