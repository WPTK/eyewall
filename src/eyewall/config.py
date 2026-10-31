"""Configuration: a TOML file under the user's config directory, tolerant to a fault.

Precedence, lowest to highest: built-in defaults, the file, command-line flags (apply_overrides). Flags never write
back to the file.

Loading never raises. A missing file is the defaults. A file that is not valid TOML is the defaults plus a warning. A
key of the wrong type or out of range is dropped with a warning and the default stands. Unknown keys are ignored
without comment, so a newer file still opens in an older build. The file is created only by save_config.

.. code-block:: toml

    [poll]                    # seconds between polls of each feed
    storms = 300
    outlook = 1800
    alerts = 300
    buoys = 600
    tides = 360
    satellite = 600
    backoff_max = 1800
    away_after = 300          # no keyboard or mouse input for this long means "away": polls slow down

    [basins]
    enabled = ["AL", "EP", "CP"]

    [nearby]                  # which stations count as "near" a storm
    radius_now_nm = 300
    radius_track_nm = 150
    track_hours = 72
    max_stations = 40

    [units]
    preset = "nautical"       # nautical, us or metric

    [watchlist]               # always shown, storm or no storm
    ndbc = ["41010", "42001", "41047"]
    coops = ["8721604"]

    [map]
    land = true
    borders = true
    cone = true
    radii = true
    glyph_set = "unicode"     # unicode or ascii (use ascii on the legacy Windows console)

    [alerts]
    new_advisory = true
    classification = true
    watches_warnings = true
    outlook = true
    buoy_thresholds = true
    bell = false

    [graphics]
    inline = "auto"           # auto or never
"""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

import tomli_w
from platformdirs import user_config_dir

from eyewall.units import DEFAULT_PRESET, PRESETS

BASINS = ("AL", "EP", "CP")
GLYPH_SETS = ("unicode", "ascii")
INLINE_MODES = ("auto", "never")
MAX_WATCHLIST = 60
_STATION_ID = re.compile(r"^[A-Za-z0-9]{3,10}$")

POLL_LIMITS: dict[str, tuple[float, float]] = {
    "storms": (60.0, 3600.0),
    "outlook": (300.0, 86400.0),
    "alerts": (60.0, 3600.0),
    "buoys": (300.0, 3600.0),
    "tides": (120.0, 3600.0),
    "satellite": (300.0, 3600.0),
    "backoff_max": (60.0, 86400.0),
    "away_after": (30.0, 86400.0),
}


@dataclass(frozen=True, slots=True)
class PollConfig:
    storms: float = 300.0
    outlook: float = 1800.0
    alerts: float = 300.0
    buoys: float = 600.0
    tides: float = 360.0
    satellite: float = 600.0
    backoff_max: float = 1800.0
    away_after: float = 300.0


@dataclass(frozen=True, slots=True)
class BasinsConfig:
    enabled: tuple[str, ...] = BASINS


@dataclass(frozen=True, slots=True)
class NearbyConfig:
    radius_now_nm: float = 300.0
    radius_track_nm: float = 150.0
    track_hours: int = 72
    max_stations: int = 40


@dataclass(frozen=True, slots=True)
class UnitsConfig:
    preset: str = DEFAULT_PRESET


@dataclass(frozen=True, slots=True)
class WatchlistConfig:
    ndbc: tuple[str, ...] = ("41010", "42001", "41047")
    coops: tuple[str, ...] = ("8721604",)


@dataclass(frozen=True, slots=True)
class MapConfig:
    land: bool = True
    borders: bool = True
    cone: bool = True
    radii: bool = True
    glyph_set: str = "unicode"


@dataclass(frozen=True, slots=True)
class AlertsConfig:
    new_advisory: bool = True
    classification: bool = True
    watches_warnings: bool = True
    outlook: bool = True
    buoy_thresholds: bool = True
    bell: bool = False


@dataclass(frozen=True, slots=True)
class GraphicsConfig:
    inline: str = "auto"


@dataclass(frozen=True, slots=True)
class Config:
    poll: PollConfig = field(default_factory=PollConfig)
    basins: BasinsConfig = field(default_factory=BasinsConfig)
    nearby: NearbyConfig = field(default_factory=NearbyConfig)
    units: UnitsConfig = field(default_factory=UnitsConfig)
    watchlist: WatchlistConfig = field(default_factory=WatchlistConfig)
    map: MapConfig = field(default_factory=MapConfig)
    alerts: AlertsConfig = field(default_factory=AlertsConfig)
    graphics: GraphicsConfig = field(default_factory=GraphicsConfig)


@dataclass(frozen=True, slots=True)
class LoadResult:
    config: Config
    warnings: tuple[str, ...] = ()
    path: Path | None = None


def default_path() -> Path:
    return Path(user_config_dir("eyewall", appauthor=False)) / "config.toml"


def _section(data: Mapping[str, Any], name: str, warnings: list[str]) -> Mapping[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        warnings.append(f"[{name}] should be a table; ignored")
        return {}
    return value


def _number(
    data: Mapping[str, Any], key: str, default: float, low: float, high: float, where: str, warnings: list[str]
) -> float:
    if key not in data:
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int | float):
        warnings.append(f"{where}.{key} should be a number; using {default:g}")
        return default
    if not low <= value <= high:
        warnings.append(f"{where}.{key} = {value:g} is outside {low:g} to {high:g}; using {default:g}")
        return default
    return float(value)


def _integer(
    data: Mapping[str, Any], key: str, default: int, low: int, high: int, where: str, warnings: list[str]
) -> int:
    if key not in data:
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        warnings.append(f"{where}.{key} should be a whole number; using {default}")
        return default
    if not low <= value <= high:
        warnings.append(f"{where}.{key} = {value} is outside {low} to {high}; using {default}")
        return default
    return value


def _flag(data: Mapping[str, Any], key: str, default: bool, where: str, warnings: list[str]) -> bool:
    if key not in data:
        return default
    value = data[key]
    if not isinstance(value, bool):
        warnings.append(f"{where}.{key} should be true or false; using {str(default).lower()}")
        return default
    return value


def _choice(
    data: Mapping[str, Any], key: str, default: str, choices: Sequence[str], where: str, warnings: list[str]
) -> str:
    if key not in data:
        return default
    value = data[key]
    if not isinstance(value, str) or value.strip().lower() not in choices:
        warnings.append(f"{where}.{key} should be one of {', '.join(choices)}; using {default}")
        return default
    return value.strip().lower()


def _ids(
    data: Mapping[str, Any], key: str, default: tuple[str, ...], where: str, warnings: list[str]
) -> tuple[str, ...]:
    """A list of station ids: upper-cased, de-duplicated, malformed entries skipped."""
    if key not in data:
        return default
    value = data[key]
    if not isinstance(value, list):
        warnings.append(f"{where}.{key} should be a list of station ids; using the default")
        return default
    ids: list[str] = []
    for item in value:
        text = str(item).strip().upper() if isinstance(item, str | int) and not isinstance(item, bool) else ""
        if not _STATION_ID.match(text):
            warnings.append(f"{where}.{key}: {item!r} is not a station id; skipped")
        elif text not in ids:
            ids.append(text)
    if len(ids) > MAX_WATCHLIST:
        warnings.append(f"{where}.{key} lists more than {MAX_WATCHLIST} stations; extras dropped")
        ids = ids[:MAX_WATCHLIST]
    return tuple(ids)


def _basins(data: Mapping[str, Any], warnings: list[str]) -> tuple[str, ...]:
    if "enabled" not in data:
        return BASINS
    value = data["enabled"]
    if not isinstance(value, list):
        warnings.append("basins.enabled should be a list of basin codes; using all three")
        return BASINS
    chosen: list[str] = []
    for item in value:
        code = item.strip().upper() if isinstance(item, str) else ""
        if code not in BASINS:
            warnings.append(f"basins.enabled: {item!r} is not one of {', '.join(BASINS)}; skipped")
        elif code not in chosen:
            chosen.append(code)
    if not chosen:
        warnings.append("basins.enabled has no valid basin; using all three")
        return BASINS
    return tuple(code for code in BASINS if code in chosen)  # canonical order


def parse_config(data: Mapping[str, Any]) -> tuple[Config, list[str]]:
    """Build a Config from parsed TOML. Never raises; problems come back as warnings."""
    warnings: list[str] = []

    sec = _section(data, "poll", warnings)
    defaults = PollConfig()
    poll = PollConfig(
        **{
            key: _number(sec, key, getattr(defaults, key), low, high, "poll", warnings)
            for key, (low, high) in POLL_LIMITS.items()
        }
    )

    basins = BasinsConfig(_basins(_section(data, "basins", warnings), warnings))

    sec = _section(data, "nearby", warnings)
    nd = NearbyConfig()
    nearby = NearbyConfig(
        radius_now_nm=_number(sec, "radius_now_nm", nd.radius_now_nm, 10, 2000, "nearby", warnings),
        radius_track_nm=_number(sec, "radius_track_nm", nd.radius_track_nm, 10, 1000, "nearby", warnings),
        track_hours=_integer(sec, "track_hours", nd.track_hours, 6, 120, "nearby", warnings),
        max_stations=_integer(sec, "max_stations", nd.max_stations, 1, 200, "nearby", warnings),
    )

    sec = _section(data, "units", warnings)
    units = UnitsConfig(_choice(sec, "preset", DEFAULT_PRESET, tuple(PRESETS), "units", warnings))

    sec = _section(data, "watchlist", warnings)
    wd = WatchlistConfig()
    watchlist = WatchlistConfig(
        ndbc=_ids(sec, "ndbc", wd.ndbc, "watchlist", warnings),
        coops=_ids(sec, "coops", wd.coops, "watchlist", warnings),
    )

    sec = _section(data, "map", warnings)
    md = MapConfig()
    map_config = MapConfig(
        land=_flag(sec, "land", md.land, "map", warnings),
        borders=_flag(sec, "borders", md.borders, "map", warnings),
        cone=_flag(sec, "cone", md.cone, "map", warnings),
        radii=_flag(sec, "radii", md.radii, "map", warnings),
        glyph_set=_choice(sec, "glyph_set", md.glyph_set, GLYPH_SETS, "map", warnings),
    )

    sec = _section(data, "alerts", warnings)
    ad = AlertsConfig()
    alerts = AlertsConfig(
        new_advisory=_flag(sec, "new_advisory", ad.new_advisory, "alerts", warnings),
        classification=_flag(sec, "classification", ad.classification, "alerts", warnings),
        watches_warnings=_flag(sec, "watches_warnings", ad.watches_warnings, "alerts", warnings),
        outlook=_flag(sec, "outlook", ad.outlook, "alerts", warnings),
        buoy_thresholds=_flag(sec, "buoy_thresholds", ad.buoy_thresholds, "alerts", warnings),
        bell=_flag(sec, "bell", ad.bell, "alerts", warnings),
    )

    sec = _section(data, "graphics", warnings)
    graphics = GraphicsConfig(_choice(sec, "inline", GraphicsConfig().inline, INLINE_MODES, "graphics", warnings))

    config = Config(poll, basins, nearby, units, watchlist, map_config, alerts, graphics)
    return config, warnings


def load_config(path: Path | None = None, *, use_file: bool = True) -> LoadResult:
    """Read the config file. With no path, the default location is used and a missing file is simply the defaults."""
    if not use_file:
        return LoadResult(Config())
    explicit = path is not None
    target = path if path is not None else default_path()
    if not target.exists():
        notes = (f"config file {target} not found; using defaults",) if explicit else ()
        return LoadResult(Config(), notes, target)
    try:
        data = tomllib.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        return LoadResult(Config(), (f"could not read {target}: {exc}; using defaults",), target)
    config, problems = parse_config(data)
    return LoadResult(config, tuple(problems), target)


def _plain(value: Any) -> Any:
    """Tuples to lists, recursively, for the TOML writer."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, tuple | list):
        return [_plain(v) for v in value]
    return value


def to_dict(config: Config) -> dict[str, Any]:
    return _plain(asdict(config))


def save_config(config: Config, path: Path | None = None) -> Path:
    """Write the whole config atomically and return the path. Comments in an existing file are not preserved."""
    target = path if path is not None else default_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=target.parent, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            tomli_w.dump(to_dict(config), handle)
        os.replace(temp_name, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp_name)
        raise
    return target


def apply_overrides(config: Config, *, basins: Sequence[str] | None = None, glyph_set: str | None = None) -> Config:
    """Command-line flags on top of the file. They are never saved."""
    if basins:
        wanted = {b.upper() for b in basins}
        chosen = tuple(code for code in BASINS if code in wanted)
        if chosen:
            config = replace(config, basins=BasinsConfig(chosen))
    if glyph_set is not None and glyph_set in GLYPH_SETS:
        config = replace(config, map=replace(config.map, glyph_set=glyph_set))
    return config
