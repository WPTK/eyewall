"""The graphics gallery's list: which images a storm has, in reading order, with the text shown beside each.

Pure data, no Textual. The forecast graphics come from the links the NHC graphics page gave (`StormState.graphics`);
the satellite stills and loops come from the NESDIS floater listing (`StormState.satellite`, plus the products the
gallery asked for when it opened).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace

from eyewall.models.graphics import FloaterProduct, GraphicKind, GraphicLink
from eyewall.state.store import StormState

# NESDIS floater product directory, and the name shown for it. `13` is the clean longwave infrared band.
SATELLITE_PRODUCTS: tuple[tuple[str, str], ...] = (
    ("GEOCOLOR", "GEOCOLOR"),
    ("AirMass", "Air mass"),
    ("13", "Infrared"),
)
IMAGE_MEDIA = frozenset({"png", "gif", "jpg", "jpeg"})

_ORDER = (
    GraphicKind.CONE,
    GraphicKind.WIND_PROBABILITY,
    GraphicKind.ARRIVAL_EARLIEST,
    GraphicKind.ARRIVAL_MOST_LIKELY,
    GraphicKind.SURGE_WATCH_WARNING,
    GraphicKind.SURGE_PEAK,
    GraphicKind.SURGE_FLOODING,
    GraphicKind.KEY_MESSAGES,
    GraphicKind.CURRENT_WIND,
    GraphicKind.RAINFALL,
    GraphicKind.RIP_CURRENTS,
)
_TITLES = {
    GraphicKind.CONE: "Cone",
    GraphicKind.WIND_PROBABILITY: "Wind probability",
    GraphicKind.ARRIVAL_EARLIEST: "Earliest arrival of winds",
    GraphicKind.ARRIVAL_MOST_LIKELY: "Most likely arrival of winds",
    GraphicKind.SURGE_WATCH_WARNING: "Storm surge watch and warning",
    GraphicKind.SURGE_PEAK: "Peak storm surge",
    GraphicKind.SURGE_FLOODING: "Storm surge flooding",
    GraphicKind.KEY_MESSAGES: "Key messages",
    GraphicKind.CURRENT_WIND: "Current wind",
    GraphicKind.RAINFALL: "Rainfall",
    GraphicKind.RIP_CURRENTS: "Rip currents",
}


@dataclass(frozen=True, slots=True)
class GalleryItem:
    """One entry in the gallery. `version` changes when a new image replaces the old one at the same address."""

    key: str
    group: str  # "forecast" or "satellite"
    title: str
    url: str
    media: str
    version: str
    loop: bool = False
    cone: bool = False

    @property
    def viewable(self) -> bool:
        """False for a KMZ or other file that has a link but no picture to draw."""
        return self.media in IMAGE_MEDIA


def _graphic_title(link: GraphicLink) -> str:
    base = _TITLES.get(link.kind, link.product)
    if link.kind is GraphicKind.WIND_PROBABILITY and link.threshold_kt is not None:
        base = f"{base} {link.threshold_kt} kt"
    elif link.kind in (GraphicKind.ARRIVAL_EARLIEST, GraphicKind.ARRIVAL_MOST_LIKELY) and link.threshold_kt is not None:
        base = f"{base} ({link.threshold_kt} kt)"
    days = link.days
    if days is None and (found := re.match(r"(\d)day", link.product)):
        days = int(found[1])
    if days is not None and link.kind in (GraphicKind.CONE, GraphicKind.WIND_PROBABILITY):
        base = f"{base}, {days} day"
    return base


def _forecast_items(links: tuple[GraphicLink, ...]) -> list[GalleryItem]:
    seen: set[tuple[str, str]] = set()
    entries: list[tuple[int, int, GraphicLink]] = []
    for link in links:
        if link.kind not in _ORDER or (link.product, link.media) in seen:
            continue
        seen.add((link.product, link.media))
        entries.append((_ORDER.index(link.kind), link.threshold_kt or 0, link))
    entries.sort(key=lambda e: (e[0], e[1], e[2].product))
    items: list[GalleryItem] = []
    titles: dict[str, int] = {}
    for _, _, link in entries:
        title = _graphic_title(link)
        if link.media not in IMAGE_MEDIA:
            title += f" ({link.media.upper()}, link only)"
        titles[title] = titles.get(title, 0) + 1
        if titles[title] > 1:
            title += f" [{link.product}]"
        items.append(
            GalleryItem(
                key=f"{link.kind.value}:{link.product}:{link.media}",
                group="forecast",
                title=title,
                url=link.url,
                media=link.media,
                version=str(link.adv_num) if link.adv_num is not None else "",
                cone=link.kind is GraphicKind.CONE,
            )
        )
    return items


def _satellite_items(code: str, label: str, product: FloaterProduct | None) -> list[GalleryItem]:
    if product is None:
        return []
    items: list[GalleryItem] = []
    still = product.still_url or product.latest_url
    if still:
        stamp = product.still_time.strftime("%Y-%m-%d %H:%MZ") if product.still_time else "latest"
        items.append(GalleryItem(f"sat:{code}:still", "satellite", f"{label} still", still, _media(still), stamp))
    if product.loop_url:
        stamp = product.still_time.isoformat() if product.still_time else "latest"
        items.append(
            GalleryItem(f"sat:{code}:loop", "satellite", f"{label} loop", product.loop_url, "gif", stamp, loop=True)
        )
    return items


def _media(url: str) -> str:
    return url.rpartition(".")[2].lower().split("?")[0]


def build_items(state: StormState, extras: Mapping[str, FloaterProduct | None] | None = None) -> list[GalleryItem]:
    """The gallery for one storm: forecast graphics first, then each satellite product's still and loop."""
    items = _forecast_items(state.graphics)
    known = {p.product.lower(): p for p in state.satellite}
    for code, label in SATELLITE_PRODUCTS:
        product = known.get(code.lower()) or (extras or {}).get(code)
        items.extend(_satellite_items(code, label, product))
    # A picture with no advisory number or time of its own is stamped with the poll that listed it, so a refreshed
    # image at the same address is fetched again (the disk cache turns an unchanged one into a 304).
    stamp = "poll:" + "/".join(str(x) for x in (state.fetched_key or ()))
    return [replace(i, version=stamp) if i.version in ("", "latest") else i for i in items]
