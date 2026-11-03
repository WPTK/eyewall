"""When the National Hurricane Center next issues a full advisory.

Full advisories come at 0300, 0900, 1500 and 2100 UTC. Intermediate advisories (the `A` and `B` suffixes) and special
advisories are not scheduled, so nothing here predicts them. The schedule is plain UTC arithmetic: no zone, no DST.
"""

from __future__ import annotations

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


def countdown(after: datetime) -> str:
    """Time to the next full advisory in one compact unit pair: 42m, 2h14m. Seconds round up, so it never shows 0m."""
    seconds = (next_issuance(after) - ensure_utc(after)).total_seconds()
    minutes = -(-int(seconds) // 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m"
