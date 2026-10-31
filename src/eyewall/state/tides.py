"""What a tide gauge says about the water: observed against predicted level, and the residual.

The residual is the observed water level minus the astronomical prediction for the same moment. Wind, pressure and surge
push it away from zero, so it is the closest thing a gauge offers to a surge estimate (it also carries ordinary
noise, a few tenths of a foot, and the gauge's own datum offsets). Pure functions over `eyewall.models.obs` records
with an explicit `now`; levels stay in feet as CO-OPS reported them.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import datetime, timedelta

from eyewall.models.obs import Prediction, TideSeries

MATCH_TOLERANCE = timedelta(minutes=6)  # a prediction counts as "the same moment" within one 6-minute step
SILENT_AFTER = timedelta(hours=2)


@dataclass(frozen=True, slots=True)
class Residual:
    """The newest water level with a prediction for its moment. All levels are feet above the series datum."""

    time: datetime
    observed_ft: float
    predicted_ft: float

    @property
    def residual_ft(self) -> float:
        return self.observed_ft - self.predicted_ft


def predicted_at(predictions: tuple[Prediction, ...], moment: datetime) -> float | None:
    """The predicted level nearest to a moment, within the match tolerance. `predictions` run soonest first."""
    times = [p.time for p in predictions]
    index = bisect.bisect_left(times, moment)
    best: Prediction | None = None
    for candidate in predictions[max(0, index - 1) : index + 1]:
        if candidate.level_ft is None or abs(candidate.time - moment) > MATCH_TOLERANCE:
            continue
        if best is None or abs(candidate.time - moment) < abs(best.time - moment):
            best = candidate
    return None if best is None else best.level_ft


def latest_residual(series: TideSeries) -> Residual | None:
    """The residual at the newest observation that has a prediction, or None when there is no pair."""
    predictions = tuple(sorted(series.predictions.items, key=lambda p: p.time))
    for reading in series.water_level.items:  # newest first
        if reading.level_ft is None:
            continue
        predicted = predicted_at(predictions, reading.time)
        if predicted is not None:
            return Residual(reading.time, reading.level_ft, predicted)
        break  # the newest reading has no prediction near it; an older pair would be misleading as "latest"
    return None


def observation_age(series: TideSeries, now: datetime) -> timedelta | None:
    """How old the newest water level is, never negative; None when the gauge has none."""
    latest = series.latest_level
    return None if latest is None else max(timedelta(0), now - latest.time)


def is_silent(series: TideSeries, now: datetime) -> bool:
    age = observation_age(series, now)
    return age is not None and age > SILENT_AFTER
