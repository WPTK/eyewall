"""Parser for `gtwo_shapefiles.zip`, the graphical tropical weather outlook.

The zip holds three layers, `gtwo_areas_<yyyymmddhhmm>` (polygons), `gtwo_lines_…` (the track the area is expected to
follow) and `gtwo_points_…` (a marker), all with the fields BASIN (`Atlantic` or `Pacific`), AREA, PROB2DAY, RISK2DAY,
PROB7DAY and RISK7DAY. Percentages are strings like `80%`. The three layers are joined on (BASIN, AREA). Invest
numbers are not in these layers; they live in the ATCF b-decks (see `atcf.py`).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from eyewall.models.outlook import OutlookGis, OutlookSystem
from eyewall.providers.nhc.gis import Feature, read_layer_group, read_layer_names

_STAMP = re.compile(r"_(?P<stamp>\d{12})$")


def _percent(value: Any) -> int | None:
    text = str(value or "").strip().rstrip("%").strip()
    return int(text) if text.isdigit() else None


def _risk(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    return text or None


def parse_gtwo_zip(data: bytes) -> OutlookGis:
    """Parse the outlook shapefile zip into one OutlookSystem per (basin, area). A quiet day gives no systems."""
    layers = read_layer_group(data, {"areas": r"^gtwo_areas_", "lines": r"^gtwo_lines_", "points": r"^gtwo_points_"})
    issued = _issued(data)
    systems: dict[tuple[str, str], dict[str, Any]] = {}

    def entry(feature: Feature) -> dict[str, Any]:
        attrs = feature.attrs
        key = (str(attrs.get("BASIN") or "").strip(), str(attrs.get("AREA") or "").strip())
        if key not in systems:
            systems[key] = {
                "attrs": attrs,
                "polygons": [],
                "lines": [],
                "point": None,
            }
        return systems[key]

    for feature in layers["areas"]:
        entry(feature)["polygons"].extend(feature.parts)
    for feature in layers["lines"]:
        entry(feature)["lines"].extend(feature.parts)
    for feature in layers["points"]:
        if feature.parts and feature.parts[0]:
            entry(feature)["point"] = feature.parts[0][0]

    built = []
    for (basin, area), parts in systems.items():
        attrs = parts["attrs"]
        built.append(
            OutlookSystem(
                basin_label=basin,
                area_id=area,
                prob_2day=_percent(attrs.get("PROB2DAY")),
                risk_2day=_risk(attrs.get("RISK2DAY")),
                prob_7day=_percent(attrs.get("PROB7DAY")),
                risk_7day=_risk(attrs.get("RISK7DAY")),
                polygons=tuple(parts["polygons"]),
                lines=tuple(parts["lines"]),
                point=parts["point"],
            )
        )
    built.sort(key=lambda s: (s.basin_label, int(s.area_id) if s.area_id.isdigit() else 0))
    return OutlookGis(issued, tuple(built))


def _issued(data: bytes) -> datetime | None:
    """The time in the layer names: `gtwo_areas_202610310507` is 2026-10-31 05:07 UTC."""
    for stem in read_layer_names(data):
        match = _STAMP.search(stem)
        if match:
            try:
                return datetime.strptime(match["stamp"], "%Y%m%d%H%M").replace(tzinfo=UTC)
            except ValueError:
                return None
    return None
