"""The replay bundle format: a directory holding a recorded storm, and the helpers that name its files.

Layout, relative to the bundle directory (the storm id is lower case, an advisory number is zero padded with an `A`
suffix for intermediates, as in NHC's own GIS file names):

    manifest.toml                      name, storm id and name, product bin, first and last moment, graphics list
    atcf/b<id>.dat                     the best track (b-deck) rows inside the recorded window
    nhc/<id>/<adv>.<kind>.txt          kind is tcm, tcp, tcd or pws; an intermediate advisory has a tcp only
    gis/<id>/<adv>_5day.zip            forecast GIS (cone, points, track, warnings)
    gis/<id>/<adv>_fcst.zip            wind radii GIS
    ndbc/activestations.xml            the recorded stations only, without the "reported in the last 8 hours" flags
    ndbc/<station>.stdmet.txt          NDBC historical rows (oldest first) inside the window
    coops/stations.<listing>.json      CO-OPS station listings (`water_level`, `met`) trimmed to the recorded gauges
    coops/<station>.<product>.json     raw datagetter answers: water_level, predictions (6-minute), wind, air_pressure
    graphics/<file>                    a few stills listed in the manifest

`scripts/record_storm.py` writes one; `eyewall.sources.replay.ReplaySource` reads one.
"""

from __future__ import annotations

import importlib.resources
import re
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import tomli_w

FORMAT = 1
MANIFEST = "manifest.toml"
TEXT_KINDS = ("tcm", "tcp", "tcd", "pws")
GIS_LAYERS = ("5day", "fcst")
TIDE_PRODUCTS = ("water_level", "predictions", "wind", "air_pressure")
TIDE_LISTINGS = ("water_level", "met")
STATIONS_XML = "ndbc/activestations.xml"
_STORM_ID = re.compile(r"(?:al|ep|cp)\d{6}")  # also the folder name under nhc/ and gis/, so nothing else is allowed


class BundleError(ValueError):
    """A bundle directory that is missing or whose manifest cannot be used."""


def text_path(storm_id: str, adv: str, kind: str) -> str:
    return f"nhc/{storm_id}/{adv}.{kind}.txt"


def gis_path(storm_id: str, adv: str, layer: str) -> str:
    return f"gis/{storm_id}/{adv}_{layer}.zip"


def bdeck_path(storm_id: str) -> str:
    return f"atcf/b{storm_id}.dat"


def ndbc_path(station_id: str) -> str:
    return f"ndbc/{station_id.upper()}.stdmet.txt"


def coops_path(station_id: str, product: str) -> str:
    return f"coops/{station_id}.{product}.json"


def coops_listing_path(listing: str) -> str:
    return f"coops/stations.{listing}.json"


@dataclass(frozen=True, slots=True)
class GraphicEntry:
    """A still image in the bundle: which advisory it belongs to and what it shows."""

    file: str
    kind: str
    product: str
    adv: str


@dataclass(frozen=True, slots=True)
class Manifest:
    name: str
    storm_id: str
    storm_name: str
    bin: str
    start: datetime
    end: datetime
    title: str = ""
    graphics: tuple[GraphicEntry, ...] = ()
    format: int = FORMAT


def _moment(value: Any, key: str) -> datetime:
    if not isinstance(value, datetime):
        raise BundleError(f"manifest.{key} should be a TOML date-time")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def read_manifest(directory: Path) -> Manifest:
    path = directory / MANIFEST
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BundleError(f"{directory}: no {MANIFEST} ({exc.strerror or exc})") from exc
    except tomllib.TOMLDecodeError as exc:
        raise BundleError(f"{path}: not valid TOML ({exc})") from exc
    try:
        graphics = tuple(
            GraphicEntry(str(g["file"]), str(g["kind"]), str(g["product"]), str(g["adv"]))
            for g in data.get("graphics", [])
        )
        storm_id = str(data["storm_id"]).lower()
        if not _STORM_ID.fullmatch(storm_id):
            raise BundleError(f"{path}: storm_id {storm_id!r} is not a storm id such as al052025")
        return Manifest(
            name=str(data["name"]),
            storm_id=storm_id,
            storm_name=str(data["storm_name"]),
            bin=str(data["bin"]).upper(),
            start=_moment(data["start"], "start"),
            end=_moment(data["end"], "end"),
            title=str(data.get("title", "")),
            graphics=graphics,
            format=int(data.get("format", FORMAT)),
        )
    except KeyError as exc:
        raise BundleError(f"{path}: missing {exc.args[0]!r}") from exc
    except (TypeError, ValueError, AttributeError) as exc:
        raise BundleError(f"{path}: a field has the wrong type or value ({exc})") from exc


def write_manifest(directory: Path, manifest: Manifest) -> None:
    data: dict[str, Any] = {
        "format": manifest.format,
        "name": manifest.name,
        "title": manifest.title,
        "storm_id": manifest.storm_id,
        "storm_name": manifest.storm_name,
        "bin": manifest.bin,
        "start": manifest.start,
        "end": manifest.end,
        "graphics": [{"file": g.file, "kind": g.kind, "product": g.product, "adv": g.adv} for g in manifest.graphics],
    }
    (directory / MANIFEST).write_text(tomli_w.dumps(data), encoding="utf-8", newline="\n")


DEMO = "demo"
DEMO_NAME = "erin2025"


def demo_bundle_path() -> Path:
    """The bundled recording of Hurricane Erin.

    A wheel carries it inside the package (`eyewall/demo/erin2025`); a source checkout keeps it with the test
    fixtures, which is where it is recorded to.
    """
    packaged = Path(str(importlib.resources.files("eyewall"))) / "demo" / DEMO_NAME
    if packaged.is_dir():
        return packaged
    checkout = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "replay" / DEMO_NAME
    if checkout.is_dir():
        return checkout
    raise BundleError("the bundled demo recording is missing from this installation")


def resolve_bundle(name: str) -> Path:
    """`demo` is the bundled recording; anything else is a bundle directory."""
    return demo_bundle_path() if name == DEMO else Path(name).expanduser()
