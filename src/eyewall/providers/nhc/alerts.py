"""api.weather.gov: tropical alerts with geometry, and the product-by-bin fallback for text.

`/alerts/active?event=…` returns a GeoJSON FeatureCollection of CAP alerts. Features without an `event` are skipped and
counted; geometry is optional (many alerts carry only affected zones). Longitudes are wrapped to (-180, 180].

`/products/types/{TCM|TCP|TCD|TCU|PWS|TWO}/locations/{AT1|EP2|CP3|AT|EP|CP}` lists a type's products newest first, and
`/products/{id}` returns one with its `productText`. The location is the product bin, never the issuing office. The
text can replace the tgftp file when tgftp fails; it starts with a bare `000` line the text parsers ignore.
"""

from __future__ import annotations

import json
from typing import Any

from eyewall.models.advisory import ApiProduct, ProductListing
from eyewall.models.watches import AlertsResult, WatchWarningAlert
from eyewall.palette import WatchWarning
from eyewall.providers.base import ParseError
from eyewall.providers.nhc.gis import wrap_lon
from eyewall.providers.nhc.times import parse_iso

_EVENT_KINDS: dict[str, WatchWarning] = {
    "tropical storm watch": WatchWarning.TROPICAL_STORM_WATCH,
    "tropical storm warning": WatchWarning.TROPICAL_STORM_WARNING,
    "hurricane watch": WatchWarning.HURRICANE_WATCH,
    "hurricane warning": WatchWarning.HURRICANE_WARNING,
    "storm surge watch": WatchWarning.SURGE_WATCH,
    "storm surge warning": WatchWarning.SURGE_WARNING,
}


def _load(data: bytes | str) -> Any:
    try:
        return json.loads(data)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ParseError(f"not JSON: {exc}") from exc


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if item)


def _rings(geometry: Any) -> tuple[tuple[tuple[float, float], ...], ...]:
    """Polygon and MultiPolygon coordinates as (lat, lon) rings."""
    if not isinstance(geometry, dict):
        return ()
    kind, coordinates = geometry.get("type"), geometry.get("coordinates")
    polygons: list[Any]
    if kind == "Polygon" and isinstance(coordinates, list):
        polygons = [coordinates]
    elif kind == "MultiPolygon" and isinstance(coordinates, list):
        polygons = list(coordinates)
    else:
        return ()
    rings: list[tuple[tuple[float, float], ...]] = []
    for polygon in polygons:
        for ring in polygon if isinstance(polygon, list) else []:
            try:
                rings.append(tuple((float(point[1]), wrap_lon(float(point[0]))) for point in ring))
            except (TypeError, ValueError, IndexError):
                continue
    return tuple(rings)


def parse_alerts(data: bytes | str) -> AlertsResult:
    """Parse the alerts feed. Raises ParseError when the payload is not a JSON object."""
    document = _load(data)
    if not isinstance(document, dict):
        raise ParseError("alerts payload is not a JSON object")
    alerts: list[WatchWarningAlert] = []
    skipped = 0
    for feature in document.get("features") or []:
        properties = feature.get("properties") if isinstance(feature, dict) else None
        if not isinstance(properties, dict) or not _text(properties.get("event")):
            skipped += 1
            continue
        raw_geocode = properties.get("geocode")
        geocode: dict[str, Any] = raw_geocode if isinstance(raw_geocode, dict) else {}
        event = str(properties["event"]).strip()
        alerts.append(
            WatchWarningAlert(
                id=_text(properties.get("id")) or _text(feature.get("id")) or "",
                event=event,
                kind=_EVENT_KINDS.get(event.lower()),
                headline=_text(properties.get("headline")),
                area_desc=_text(properties.get("areaDesc")) or "",
                severity=_text(properties.get("severity")),
                urgency=_text(properties.get("urgency")),
                certainty=_text(properties.get("certainty")),
                status=_text(properties.get("status")),
                message_type=_text(properties.get("messageType")),
                sender_name=_text(properties.get("senderName")),
                sent=parse_iso(properties.get("sent")),
                effective=parse_iso(properties.get("effective")),
                onset=parse_iso(properties.get("onset")),
                expires=parse_iso(properties.get("expires")),
                ends=parse_iso(properties.get("ends")),
                description=_text(properties.get("description")),
                instruction=_text(properties.get("instruction")),
                zones=_strings(properties.get("affectedZones")),
                same_codes=_strings(geocode.get("SAME")),
                rings=_rings(feature.get("geometry")),
            )
        )
    return AlertsResult(tuple(alerts), parse_iso(document.get("updated")), skipped)


def parse_product_list(data: bytes | str) -> tuple[ProductListing, ...]:
    """The products in an api.weather.gov product list, in the order served (newest first)."""
    document = _load(data)
    if not isinstance(document, dict):
        raise ParseError("product list is not a JSON object")
    listing: list[ProductListing] = []
    for item in document.get("@graph") or []:
        if isinstance(item, dict) and _text(item.get("id")):
            listing.append(
                ProductListing(
                    id=str(item["id"]),
                    code=_text(item.get("productCode")),
                    name=_text(item.get("productName")),
                    office=_text(item.get("issuingOffice")),
                    wmo_id=_text(item.get("wmoCollectiveId")),
                    issued=parse_iso(item.get("issuanceTime")),
                )
            )
    return tuple(listing)


def parse_product(data: bytes | str) -> ApiProduct:
    """One api.weather.gov product. Raises ParseError when it has no id or no `productText`."""
    document = _load(data)
    if not isinstance(document, dict) or not _text(document.get("id")) or "productText" not in document:
        raise ParseError("not an api.weather.gov product")
    return ApiProduct(
        id=str(document["id"]),
        code=_text(document.get("productCode")),
        office=_text(document.get("issuingOffice")),
        wmo_id=_text(document.get("wmoCollectiveId")),
        issued=parse_iso(document.get("issuanceTime")),
        text=str(document.get("productText") or ""),
    )
