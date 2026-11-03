"""When the National Hurricane Center next issues a full advisory.

Full advisories come at 0300, 0900, 1500 and 2100 UTC. Intermediate advisories (the `A` and `B` suffixes) and special
advisories are not scheduled, so nothing here predicts them. The schedule is plain UTC arithmetic: no zone, no DST.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from eyewall.clock import ensure_utc

ISSUANCE_HOURS = (3, 9, 15, 21)


def next_issuance(after: datetime) -> datetime:
    """The first full-advisory time strictly after `after`, always within six hours, as UTC."""
    moment = ensure_utc(after)
    for hour in ISSUANCE_HOURS:
        candidate = moment.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate > moment:
            return candidate
    return datetime.combine(moment.date() + timedelta(days=1), datetime.min.time(), UTC).replace(hour=ISSUANCE_HOURS[0])


def previous_issuance(at: datetime) -> datetime:
    """The latest full-advisory time at or before `at`, as UTC."""
    later = next_issuance(at)
    # the slots are 6 h apart, so the one before the next is the latest at or before `at`
    return later - timedelta(hours=6)


def countdown(after: datetime) -> str:
    """Time to the next full advisory in one compact unit pair: 42m, 2h14m. Seconds round up, so it never shows 0m."""
    seconds = (next_issuance(after) - ensure_utc(after)).total_seconds()
    hours, minutes = divmod(math.ceil(seconds / 60), 60)
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m"


OVERDUE_LIMIT = timedelta(hours=3)  # past this a missing advisory is a dead feed, which the freshness state reports


def advisory_status(now: datetime, newest: datetime | None) -> str:
    """The bar text: the countdown, or "overdue" while the latest slot has passed with no advisory at or after it seen.

    `newest` is the issue time of the newest advisory on any active storm; None means none is known, which counts as
    nothing overdue."""
    slot = previous_issuance(now)
    late = ensure_utc(now) - slot
    if newest is not None and ensure_utc(newest) < slot and late <= OVERDUE_LIMIT:
        minutes = int(late.total_seconds() // 60)
        return f"full advisory overdue {minutes}m" if minutes else "full advisory due"
    return f"next full advisory {countdown(now)}"
