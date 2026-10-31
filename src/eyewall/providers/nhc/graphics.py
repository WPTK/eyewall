"""Links to NOAA graphics: the NHC forecast graphics page and the NESDIS floater directory listings.

The NHC page (`forecastGraphics.url` in CurrentStorms.json, for example `…/graphics_at5.shtml`) links to cone, wind
probability, arrival time and surge images. Its exact markup is confirmed during the first live storm (the quiet-day
page only holds a placeholder), so the parser is deliberately loose: it takes every image or KMZ path anywhere in the
document, resolves it against the page URL, and classifies it by the product name in the file name
(`5day_cone_with_line_and_wind`, `earliest_reasonable_toa_34`, `wsp34knt120hr_5km`...). Site chrome and placeholders are
left out. The same code reads the archived per-storm graphics pages, which list one image per advisory.

The NESDIS listings are Apache directory pages: `FLOATER/data/` lists storms, `FLOATER/data/AL052025/` lists products
(GEOCOLOR, AirMass, 01..16...), and a product directory lists time-stamped stills (`2026298 1500` as `20262981500`, year
and day of year and UTC time), ranged loops and the full loop `AL052025-GEOCOLOR-1000x1000.gif`.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import unquote, urljoin, urlsplit

from eyewall.models.graphics import FloaterProduct, GraphicKind, GraphicLink
from eyewall.providers.nhc.ids import floater_url, parse_adv_num, parse_storm_id

_ASSET = re.compile(r"[A-Za-z0-9_./:+%~\-]+\.(?:png|gif|jpe?g|kmz|kml)(?![A-Za-z0-9])", re.IGNORECASE)
_CHROME = ("/css/", "/assets/", "/images/", "notready", "logo", "skipgraphic", "usa_gov", "thumb", "favicon", "icon")
_LEADING_STAMP = re.compile(r"^\d{4,}_")
_LEADING_STORM = re.compile(r"^(?:al|ep|cp)\d{6}[_-]", re.IGNORECASE)
_TRAILING_ADV = re.compile(r"[_-](?P<adv>\d{1,3}[A-Za-z]?)$")
_THRESHOLD_STEM = re.compile(r"(?:toa|probs?|wsp)$", re.IGNORECASE)
_LISTING_HREF = re.compile(r'<a href="(?P<href>[^"?]+)"', re.IGNORECASE)


def _classify(product: str) -> tuple[GraphicKind, int | None, int | None]:
    """The kind of a product name, with the forecast days and wind threshold when the name carries them."""
    name = product.lower()
    days_match = re.search(r"(\d)day", name)
    days = int(days_match[1]) if days_match else None
    threshold_match = re.search(r"wind_probs?_(\d{2})|wsp(\d{2})knt|(?:^|_)(34|50|64)(?:_wsp|kt)|_toa_(\d{2})", name)
    threshold = next((int(g) for g in (threshold_match.groups() if threshold_match else ()) if g), None)
    if "earliest_reasonable_toa" in name:
        return GraphicKind.ARRIVAL_EARLIEST, days, threshold
    if "most_likely_toa" in name:
        return GraphicKind.ARRIVAL_MOST_LIKELY, days, threshold
    if "cone" in name:
        return GraphicKind.CONE, days, threshold
    if "wind_prob" in name or "wsp" in name:
        return GraphicKind.WIND_PROBABILITY, days, threshold
    if "peak_surge" in name or "peaksurge" in name:
        return GraphicKind.SURGE_PEAK, days, threshold
    if "surge" in name and ("flood" in name or "inundation" in name):
        return GraphicKind.SURGE_FLOODING, days, threshold
    if "surge" in name:
        return GraphicKind.SURGE_WATCH_WARNING, days, threshold
    if "key_messages" in name:
        return GraphicKind.KEY_MESSAGES, days, threshold
    if "current_wind" in name:
        return GraphicKind.CURRENT_WIND, days, threshold
    if "rain" in name or "qpf" in name:
        return GraphicKind.RAINFALL, days, threshold
    if "rip" in name:
        return GraphicKind.RIP_CURRENTS, days, threshold
    return GraphicKind.OTHER, days, threshold


def parse_graphics_page(html: str | bytes, base_url: str) -> tuple[GraphicLink, ...]:
    """Every graphic linked from a forecast graphics page, in page order without duplicates.

    Links to anything that is not recognisably a storm graphic (logos, placeholders) are dropped. A page for a quiet
    day gives an empty tuple.
    """
    text = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
    seen: set[str] = set()
    links: list[GraphicLink] = []
    for match in _ASSET.finditer(text):
        url = urljoin(base_url, match.group(0))
        if url in seen:
            continue
        seen.add(url)
        path = unquote(urlsplit(url).path)
        lowered = path.lower()
        if any(token in lowered for token in _CHROME):
            continue
        filename = path.rsplit("/", 1)[-1]
        stem, _, extension = filename.rpartition(".")
        product = _LEADING_STORM.sub("", _LEADING_STAMP.sub("", stem))
        adv = _TRAILING_ADV.search(product)
        adv_num = None
        # A trailing number is an advisory unless it is the threshold of a probability or arrival-time product.
        if adv is not None and not _THRESHOLD_STEM.search(product[: adv.start()]):
            adv_num = parse_adv_num(adv["adv"])
            product = product[: adv.start()]
        kind, days, threshold = _classify(product)
        if kind is GraphicKind.OTHER and "storm_graphics" not in lowered and "/graphics/" not in lowered:
            continue
        links.append(
            GraphicLink(
                kind=kind,
                product=product,
                url=url,
                media=extension.lower().replace("jpeg", "jpg"),
                adv_num=adv_num,
                days=days,
                threshold_kt=threshold,
            )
        )
    return tuple(links)


# ---- NESDIS floater -----------------------------------------------------------------------------------------------


def _hrefs(html: str | bytes) -> list[str]:
    text = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
    return [match["href"] for match in _LISTING_HREF.finditer(text)]


def parse_floater_storms(html: str | bytes) -> tuple[str, ...]:
    """Storm ids (`AL052025`) listed in the `FLOATER/data/` directory page, in listing order."""
    found = []
    for href in _hrefs(html):
        name = href.strip("/")
        if re.fullmatch(r"(?:AL|EP|CP)\d{6}", name):
            found.append(name)
    return tuple(found)


def parse_floater_products(html: str | bytes) -> tuple[str, ...]:
    """Product directory names (`GEOCOLOR`, `AirMass`, `01`...) listed in a storm's floater directory page."""
    found = []
    for href in _hrefs(html):
        if href.endswith("/") and not href.startswith(("..", "/", "?")):
            found.append(href.rstrip("/"))
    return tuple(found)


def _stamp(text: str) -> datetime | None:
    try:
        return datetime.strptime(text, "%Y%j%H%M").replace(tzinfo=UTC)
    except ValueError:
        return None


def parse_floater_listing(html: str | bytes, storm_id: str, product: str, *, size: str = "1000x1000") -> FloaterProduct:
    """The newest still and the loop in a product directory page.

    `still_url` is the newest time-stamped still of the given size; `latest_url` is the rolling copy NESDIS keeps
    (`latest.jpg`, or the unstamped `1000x1000.jpg`); `loop_url` is the full loop `<ID>-<PRODUCT>-1000x1000.gif`, or the
    newest time-ranged loop when only those exist.
    """
    base = floater_url(storm_id, product)
    names = [href for href in _hrefs(html) if not href.endswith("/") and not href.startswith(("..", "/", "?"))]
    stills = [
        (when, name)
        for name in names
        if (m := re.match(rf"^(?P<stamp>\d{{11}})_.*-{size}\.jpg$", name)) and (when := _stamp(m["stamp"])) is not None
    ]
    ranged = [
        (end, start, name)
        for name in names
        if (m := re.match(rf"^(?P<start>\d{{11}})-(?P<end>\d{{11}})-.*-{size}\.gif$", name))
        and (start := _stamp(m["start"])) is not None
        and (end := _stamp(m["end"])) is not None
    ]
    full_loop = next(
        (name for name in names if re.match(rf"^(?:AL|EP|CP)\d{{6}}-.*-{size}\.gif$", name, re.IGNORECASE)), None
    )
    latest = next((name for name in ("latest.jpg", f"{size}.jpg") if name in names), None)
    newest_still = max(stills) if stills else None
    newest_loop = max(ranged) if ranged else None
    loop_name = full_loop or (newest_loop[2] if newest_loop else None)
    return FloaterProduct(
        storm_id=parse_storm_id(storm_id).lower,
        product=product,
        base_url=base,
        still_url=base + newest_still[1] if newest_still else None,
        still_time=newest_still[0] if newest_still else None,
        latest_url=base + latest if latest else None,
        loop_url=base + loop_name if loop_name else None,
        loop_start=newest_loop[1] if newest_loop and not full_loop else None,
        loop_end=newest_loop[0] if newest_loop and not full_loop else None,
    )
