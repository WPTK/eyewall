from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st

from eyewall.issuance import ISSUANCE_HOURS, advisory_status, countdown, next_issuance

moments = st.datetimes(min_value=datetime(2000, 1, 1), max_value=datetime(2100, 1, 1)).map(
    lambda d: d.replace(tzinfo=UTC)
)


@given(moments)
def test_next_issuance_is_strictly_after_within_six_hours_and_on_a_schedule_hour(t: datetime) -> None:
    n = next_issuance(t)
    assert t < n <= t + timedelta(hours=6)
    assert n.hour in ISSUANCE_HOURS and n.minute == n.second == n.microsecond == 0


@given(moments)
def test_countdown_never_reads_zero(t: datetime) -> None:
    assert countdown(t) != "0m"


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 9, 1, 2, 59, 59, tzinfo=UTC), datetime(2026, 9, 1, 3, tzinfo=UTC)),
        (datetime(2026, 9, 1, 3, tzinfo=UTC), datetime(2026, 9, 1, 9, tzinfo=UTC)),  # at the hour, the next one
        (datetime(2026, 9, 1, 21, 30, tzinfo=UTC), datetime(2026, 9, 2, 3, tzinfo=UTC)),  # the 2100Z to 0300Z gap
        (datetime(2026, 12, 31, 23, 59, tzinfo=UTC), datetime(2027, 1, 1, 3, tzinfo=UTC)),  # across the year
        (datetime(2026, 2, 28, 22, tzinfo=UTC), datetime(2026, 3, 1, 3, tzinfo=UTC)),
    ],
)
def test_known_rollovers(now: datetime, expected: datetime) -> None:
    assert next_issuance(now) == expected


def test_a_local_zone_is_converted_not_trusted() -> None:
    edt = timezone(timedelta(hours=-4))
    assert next_issuance(datetime(2026, 9, 1, 22, 0, tzinfo=edt)) == datetime(2026, 9, 2, 3, tzinfo=UTC)  # 0200Z


def test_countdown_text() -> None:
    assert countdown(datetime(2026, 9, 1, 0, 46, tzinfo=UTC)) == "2h14m"
    assert countdown(datetime(2026, 9, 1, 2, 18, 30, tzinfo=UTC)) == "42m"
    assert countdown(datetime(2026, 9, 1, 2, 59, 59, tzinfo=UTC)) == "1m"
    assert countdown(datetime(2026, 9, 1, 3, tzinfo=UTC)) == "6h00m"


def test_a_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError):
        next_issuance(datetime(2026, 9, 1, 2, 0))


def test_countdown_minutes_round_up_at_the_boundary() -> None:
    slot = datetime(2026, 9, 1, 3, tzinfo=UTC)
    assert countdown(slot - timedelta(seconds=59.9)) == "1m"
    assert countdown(slot - timedelta(seconds=60)) == "1m"
    assert countdown(slot - timedelta(seconds=60.5)) == "2m"


def test_overdue_follows_the_newest_advisory_seen() -> None:
    slot = datetime(2026, 9, 2, 3, tzinfo=UTC)
    last = datetime(2026, 9, 1, 21, tzinfo=UTC)
    assert advisory_status(slot - timedelta(minutes=2), last) == "next full advisory 2m"  # just before
    assert advisory_status(slot + timedelta(minutes=5), last) == "full advisory overdue 5m"  # late
    assert advisory_status(slot + timedelta(seconds=20), last) == "full advisory due"
    assert advisory_status(slot + timedelta(minutes=5), slot) == "next full advisory 5h55m"  # it arrived
    assert advisory_status(slot + timedelta(minutes=5), None) == "next full advisory 5h55m"  # nothing known
    assert advisory_status(slot + timedelta(hours=3, minutes=1), last).startswith("next full")  # a dead feed
