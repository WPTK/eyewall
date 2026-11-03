"""Rapid intensification from b-deck fixes: maximum sustained wind up by RI_GAIN_KT or more over RI_WINDOW.

This is the NHC definition. The pressure fall is deliberately not a second signal: there is no single threshold the
NHC publishes for it that holds across latitudes and starting pressures, so a made-up one would flag noise.

For each fix the 24 h earlier value is the fix at exactly that time when there is one, otherwise the two nearest fixes
bracketing it, linearly interpolated. Nothing is extrapolated: a fix with no fix at or before its 24 h mark has no
answer, and neither has one whose bracketing fixes are more than MAX_GAP apart (an intermediate-fix gap in the file).
Fixes with no wind (0 in the file, None here) are skipped, so a gap they leave is judged by the same MAX_GAP rule.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from eyewall.models.track import BestTrackFix

RI_GAIN_KT = 30
RI_WINDOW = timedelta(hours=24)
MAX_GAP = timedelta(hours=12)


@dataclass(frozen=True, slots=True)
class Intensification:
    """The wind gain ending at `end`, measured against `start` (the 24 h mark, or the interpolated value there)."""

    end: datetime
    gain_kt: float

    @property
    def is_rapid(self) -> bool:
        return self.gain_kt >= RI_GAIN_KT


def _winds(fixes: Sequence[BestTrackFix]) -> list[tuple[datetime, int]]:
    """One (time, wind) per time, ordered, without the fixes that carry no wind."""
    by_time: dict[datetime, int] = {}
    for fix in fixes:
        if fix.vmax_kt is not None:
            by_time[fix.time] = fix.vmax_kt
    return sorted(by_time.items())


def _gain(winds: list[tuple[datetime, int]], index: int) -> float | None:
    end, now = winds[index]
    target = end - RI_WINDOW
    for j in range(index - 1, -1, -1):
        when, value = winds[j]
        if when == target:
            return now - value
        if when < target:
            after_when, after_value = winds[j + 1]
            span = after_when - when
            if span > MAX_GAP or after_when > end:
                return None
            fraction = (target - when) / span
            return now - (value + (after_value - value) * fraction)
    return None


def intensification(fixes: Sequence[BestTrackFix]) -> list[Intensification]:
    """The 24 h wind gain at every fix that has one, oldest first."""
    winds = _winds(fixes)
    out: list[Intensification] = []
    for i in range(len(winds)):
        gain = _gain(winds, i)
        if gain is not None:
            out.append(Intensification(winds[i][0], gain))
    return out


def current_rapid(fixes: Sequence[BestTrackFix]) -> Intensification | None:
    """The newest fix's gain when it is rapid, else None."""
    winds = _winds(fixes)
    if not winds:
        return None
    gain = _gain(winds, len(winds) - 1)
    if gain is None or gain < RI_GAIN_KT:
        return None
    return Intensification(winds[-1][0], gain)


def episode_start(fixes: Sequence[BestTrackFix]) -> datetime | None:
    """When the rapid episode the newest fix is in began: the first fix of its unbroken run of rapid fixes.

    None when the newest fix is not rapid. Stable while the episode lasts, so it can key an event.
    """
    steps = intensification(fixes)
    if not steps or not steps[-1].is_rapid or steps[-1].end != _winds(fixes)[-1][0]:
        return None
    start = steps[-1].end
    for step in reversed(steps):
        if not step.is_rapid:
            break
        start = step.end
    return start
