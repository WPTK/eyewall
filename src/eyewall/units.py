"""Unit conversion and display presets.

Values stay in the unit NOAA reported them in and are converted only for display. NHC speaks knots, millibars and
nautical miles; NDBC speaks metres per second and hectopascals; the CurrentStorms feed gives movement in mph. Callers
name the source unit explicitly so none of that is guessed.
"""

from __future__ import annotations

from dataclasses import dataclass

# How many base units one of each unit equals. Bases: m/s, hPa, km, m.
_WIND = {"kt": 1852.0 / 3600.0, "mph": 0.44704, "kmh": 1.0 / 3.6, "mps": 1.0}
_PRESSURE = {"mb": 1.0, "hpa": 1.0, "inhg": 33.8638866667}
_DISTANCE = {"nm": 1.852, "km": 1.0, "mi": 1.609344}
_LENGTH = {"m": 1.0, "ft": 0.3048}
_TEMPERATURE = ("c", "f")

_FACTORS: dict[str, tuple[str, float]] = {}
for _dimension, _table in (("wind", _WIND), ("pressure", _PRESSURE), ("distance", _DISTANCE), ("length", _LENGTH)):
    for _unit, _factor in _table.items():
        _FACTORS[_unit] = (_dimension, _factor)
for _unit in _TEMPERATURE:
    _FACTORS[_unit] = ("temperature", 1.0)

LABELS = {
    "kt": "kt",
    "mph": "mph",
    "kmh": "km/h",
    "mps": "m/s",
    "mb": "mb",
    "hpa": "hPa",
    "inhg": "inHg",
    "nm": "nm",
    "km": "km",
    "mi": "mi",
    "m": "m",
    "ft": "ft",
    "c": "°C",
    "f": "°F",
}

_DECIMALS = {"mps": 1, "inhg": 2, "m": 1, "c": 1}
MISSING = "--"


class UnitError(ValueError):
    """An unknown unit, or a conversion between different kinds of unit."""


def dimension(unit: str) -> str:
    """One of wind, pressure, distance, length or temperature."""
    try:
        return _FACTORS[unit][0]
    except KeyError:
        raise UnitError(f"unknown unit {unit!r}") from None


def convert(value: float, source: str, target: str) -> float:
    """Convert a value from one unit to another; both must measure the same thing."""
    if dimension(source) != dimension(target):
        raise UnitError(f"cannot convert {source} to {target}")
    if source == target:
        return value
    if dimension(source) == "temperature":
        return value * 9.0 / 5.0 + 32.0 if source == "c" else (value - 32.0) * 5.0 / 9.0
    return value * _FACTORS[source][1] / _FACTORS[target][1]


def format_value(value: float | None, unit: str, *, decimals: int | None = None, label: bool = True) -> str:
    """Format as 100 kt or 29.92 inHg. A missing value is shown as --."""
    if value is None:
        return MISSING
    if decimals is None:
        decimals = _DECIMALS.get(unit, 0)
        if dimension(unit) == "distance" and abs(value) < 10:
            decimals = 1
    text = f"{value:.{decimals}f}"
    if text.startswith("-") and float(text) == 0:
        text = text[1:]  # never show a negative zero
    return f"{text} {LABELS[unit]}" if label else text


@dataclass(frozen=True, slots=True)
class Preset:
    """The units one reader wants to see."""

    name: str
    wind: str
    pressure: str
    distance: str
    length: str
    temperature: str

    def fmt_wind(self, value: float | None, unit: str = "kt", *, decimals: int | None = None) -> str:
        return format_value(None if value is None else convert(value, unit, self.wind), self.wind, decimals=decimals)

    def fmt_pressure(self, value: float | None, unit: str = "mb", *, decimals: int | None = None) -> str:
        converted = None if value is None else convert(value, unit, self.pressure)
        return format_value(converted, self.pressure, decimals=decimals)

    def fmt_distance(self, value: float | None, unit: str = "nm", *, decimals: int | None = None) -> str:
        converted = None if value is None else convert(value, unit, self.distance)
        return format_value(converted, self.distance, decimals=decimals)

    def fmt_length(self, value: float | None, unit: str = "m", *, decimals: int | None = None) -> str:
        converted = None if value is None else convert(value, unit, self.length)
        return format_value(converted, self.length, decimals=decimals)

    def fmt_temperature(self, value: float | None, unit: str = "c", *, decimals: int | None = None) -> str:
        converted = None if value is None else convert(value, unit, self.temperature)
        return format_value(converted, self.temperature, decimals=decimals)


PRESETS: dict[str, Preset] = {
    "nautical": Preset("nautical", wind="kt", pressure="mb", distance="nm", length="ft", temperature="f"),
    "us": Preset("us", wind="mph", pressure="inhg", distance="mi", length="ft", temperature="f"),
    "metric": Preset("metric", wind="kmh", pressure="hpa", distance="km", length="m", temperature="c"),
}
DEFAULT_PRESET = "nautical"


def next_preset(name: str) -> str:
    """The preset after the given one, cycling nautical, us, metric. An unknown name starts the cycle."""
    names = list(PRESETS)
    if name not in names:
        return names[0]
    return names[(names.index(name) + 1) % len(names)]
