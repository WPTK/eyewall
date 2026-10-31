"""Storm ids, product bins, advisory numbers and every URL the NHC providers fetch.

Identity rules, all observed in the feeds:

- Storm ids are `al052025` in CurrentStorms.json and ATCF file names, `AL052025` in product headers and NESDIS paths.
  eyewall keys on the lower-case form.
- A product bin (`AT1`..`AT5`, `EP1`..`EP5`, `CP1`..`CP5`) is reused within a season and says nothing about the storm. A
  storm that crosses 140 W keeps its `ep` id but moves to a `CP` bin.
- Advisory numbers carry an `A` suffix for intermediate advisories (`018A`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import quote

from eyewall.models.storm import AdvNum, Basin, ProductRef, Storm

TGFTP_BASE = "https://tgftp.nws.noaa.gov/data/raw"
NHC_BASE = "https://www.nhc.noaa.gov"
FTP_BASE = "https://ftp.nhc.noaa.gov"
API_BASE = "https://api.weather.gov"
FLOATER_BASE = "https://cdn.star.nesdis.noaa.gov/FLOATER/data"

CURRENT_STORMS_URL = f"{NHC_BASE}/CurrentStorms.json"
GTWO_ZIP_URL = f"{NHC_BASE}/xgtwo/gtwo_shapefiles.zip"
BTK_INDEX_URL = f"{FTP_BASE}/atcf/btk/"

# The event names api.weather.gov uses for tropical products, in the order the alerts query lists them.
ALERT_EVENTS: tuple[str, ...] = (
    "Hurricane Warning",
    "Hurricane Watch",
    "Tropical Storm Warning",
    "Tropical Storm Watch",
    "Storm Surge Warning",
    "Storm Surge Watch",
    "Hurricane Force Wind Warning",
    "Extreme Wind Warning",
    "Tropical Cyclone Statement",
)

_STORM_ID = re.compile(r"^(?P<basin>al|ep|cp)(?P<number>\d{2})(?P<year>\d{4})$", re.IGNORECASE)
_ADV_NUM = re.compile(r"^\s*0*(?P<number>\d+)\s*(?P<suffix>[A-Za-z]?)\s*$")
_BIN = re.compile(r"^(?P<prefix>AT|EP|CP)(?P<index>[1-5])$", re.IGNORECASE)


class ProductKind(StrEnum):
    """Text product types, spelled as in tgftp file names and api.weather.gov product types."""

    TCM = "TCM"
    TCP = "TCP"
    TCD = "TCD"
    TCU = "TCU"
    PWS = "PWS"
    TWO = "TWO"


@dataclass(frozen=True, slots=True)
class StormId:
    basin: Basin
    number: int
    year: int

    @property
    def lower(self) -> str:
        return f"{self.basin.value.lower()}{self.number:02d}{self.year}"

    @property
    def upper(self) -> str:
        return self.lower.upper()

    @property
    def is_invest(self) -> bool:
        return 90 <= self.number <= 99


def parse_storm_id(text: str) -> StormId:
    """Parse `al052025` or `AL052025`. Raises ValueError for anything else."""
    match = _STORM_ID.match(text.strip())
    if match is None:
        raise ValueError(f"not a storm id: {text!r}")
    return StormId(Basin(match["basin"].upper()), int(match["number"]), int(match["year"]))


def normalize_storm_id(text: str) -> str:
    """The lower-case form eyewall keys on. Raises ValueError for a malformed id."""
    return parse_storm_id(text).lower


def parse_adv_num(value: object) -> AdvNum | None:
    """`030`, `18a`, `5` or the integer 5 to an AdvNum; None for anything that is not an advisory number."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return AdvNum(value) if value >= 0 else None
    if not isinstance(value, str):
        return None
    match = _ADV_NUM.match(value)
    if match is None:
        return None
    return AdvNum(int(match["number"]), match["suffix"].upper())


def format_adv_num(adv: AdvNum, width: int = 3) -> str:
    """The zero-padded form used in GIS and archive file names: `030`, `030A`."""
    return f"{adv.number:0{width}d}{adv.suffix}"


@dataclass(frozen=True, slots=True)
class Bin:
    """A product bin such as AT5. `index` is 1 to 5."""

    prefix: str
    index: int

    @property
    def name(self) -> str:
        return f"{self.prefix}{self.index}"

    @property
    def basin(self) -> Basin:
        return Basin.AL if self.prefix == "AT" else Basin(self.prefix)


def parse_bin(text: str) -> Bin:
    """Parse `AT1`..`AT5`, `EP1`..`EP5`, `CP1`..`CP5` (any case). Raises ValueError for anything else."""
    match = _BIN.match(text.strip())
    if match is None:
        raise ValueError(f"not a product bin: {text!r}")
    return Bin(match["prefix"].upper(), int(match["index"]))


def bins_for(basin: Basin) -> tuple[Bin, ...]:
    prefix = "AT" if basin is Basin.AL else basin.value
    return tuple(Bin(prefix, index) for index in range(1, 6))


# ---- tgftp raw text -----------------------------------------------------------------------------------------------

# (directory, WMO heading prefix, office) per bin prefix. The heading carries the bin index in its last digit.
_TGFTP_PREFIX = {"AT": ("wtnt", "knhc"), "EP": ("wtpz", "knhc"), "CP": ("wtpa", "phfo")}
_PWS_PREFIX = {"AT": ("font", "knhc"), "EP": ("fopz", "knhc"), "CP": ("fopa", "phfo")}
_SERIES = {ProductKind.TCM: 2, ProductKind.TCP: 3, ProductKind.TCD: 4, ProductKind.TCU: 6}


def tgftp_url(kind: ProductKind, bin_: Bin) -> str:
    """The tgftp URL of a storm product: `wt/wtnt22.knhc.tcm.at2.txt`, `fo/fopz13.knhc.pws.ep3.txt`."""
    if kind is ProductKind.TWO:
        raise ValueError("outlooks are per basin, use outlook_url")
    suffix = f"{kind.value.lower()}.{bin_.prefix.lower()}{bin_.index}"
    if kind is ProductKind.PWS:
        head, office = _PWS_PREFIX[bin_.prefix]
        return f"{TGFTP_BASE}/fo/{head}1{bin_.index}.{office}.{suffix}.txt"
    head, office = _TGFTP_PREFIX[bin_.prefix]
    return f"{TGFTP_BASE}/wt/{head}{_SERIES[kind]}{bin_.index}.{office}.{suffix}.txt"


def outlook_url(basin: Basin) -> str:
    """The tgftp URL of the tropical weather outlook text for a basin."""
    return {
        Basin.AL: f"{TGFTP_BASE}/ab/abnt20.knhc.two.at.txt",
        Basin.EP: f"{TGFTP_BASE}/ab/abpz20.knhc.two.ep.txt",
        Basin.CP: f"{TGFTP_BASE}/ac/acpn50.phfo.two.cp.txt",
    }[basin]


def outlook_location(basin: Basin) -> str:
    """The api.weather.gov location of a basin's outlook: AT, EP or CP."""
    return "AT" if basin is Basin.AL else basin.value


# ---- api.weather.gov ----------------------------------------------------------------------------------------------


def api_products_url(kind: ProductKind, location: str) -> str:
    """The product list for a type at a location. The location is a bin (`AT1`) or a basin (`AT`), never KNHC."""
    return f"{API_BASE}/products/types/{kind.value}/locations/{quote(location.upper())}"


def api_product_url(product_id: str) -> str:
    return f"{API_BASE}/products/{quote(product_id)}"


def alerts_url() -> str:
    return f"{API_BASE}/alerts/active"


def alerts_params() -> dict[str, str]:
    return {"event": ",".join(ALERT_EVENTS)}


# ---- ATCF ---------------------------------------------------------------------------------------------------------


def bdeck_name(storm_id: str) -> str:
    """`al052025` to `bal052025.dat`. CP storms are `bcp…` files in the same directory."""
    return f"b{normalize_storm_id(storm_id)}.dat"


def bdeck_url(storm_id: str) -> str:
    return f"{FTP_BASE}/atcf/btk/{bdeck_name(storm_id)}"


def bdeck_archive_url(storm_id: str) -> str:
    """The gzipped final b-deck in the yearly archive, for replay bundles."""
    parsed = parse_storm_id(storm_id)
    return f"{FTP_BASE}/atcf/archive/{parsed.year}/{bdeck_name(storm_id)}.gz"


# ---- GIS ----------------------------------------------------------------------------------------------------------


def forecast_zip_url(storm_id: str, adv: AdvNum | None, layer: str = "5day") -> str:
    """`…/gis/forecast/archive/al052025_5day_030A.zip`; `adv=None` gives the `latest` copy. Layer is 5day or fcst."""
    suffix = "latest" if adv is None else format_adv_num(adv)
    return f"{NHC_BASE}/gis/forecast/archive/{normalize_storm_id(storm_id)}_{layer}_{suffix}.zip"


def best_track_zip_url(storm_id: str) -> str:
    return f"{NHC_BASE}/gis/best_track/{normalize_storm_id(storm_id)}_best_track.zip"


def gtwo_archive_zip_url(basin: str, issuance: str) -> str:
    """An archived outlook shapefile zip (the 2023 to 2025 per-basin layout): basin is atl, epac or cpac."""
    return f"{NHC_BASE}/archive/xgtwo/{basin}/{issuance}/gtwo_shapefiles.zip"


# ---- NHC archive pages (replay and fixture recording only) --------------------------------------------------------

ARCHIVE_KINDS = ("fstadv", "public", "discus", "wndprb")


def archive_product_url(kind: str, storm_id: str, adv: AdvNum) -> str:
    """`…/archive/2025/al05/al052025.fstadv.030.shtml`. Kind is fstadv, public, discus or wndprb."""
    if kind not in ARCHIVE_KINDS:
        raise ValueError(f"unknown archive product {kind!r}")
    parsed = parse_storm_id(storm_id)
    lower = parsed.lower
    return f"{NHC_BASE}/archive/{parsed.year}/{lower[:4]}/{lower}.{kind}.{format_adv_num(adv)}.shtml"


# ---- graphics -----------------------------------------------------------------------------------------------------


def graphics_landing_url(bin_: Bin) -> str:
    """`https://www.nhc.noaa.gov/graphics_at1.shtml`. CurrentStorms gives the exact URL; this is the fallback."""
    return f"{NHC_BASE}/graphics_{bin_.name.lower()}.shtml"


def cone_kmz_url(storm_id: str) -> str:
    return f"{NHC_BASE}/storm_graphics/api/{parse_storm_id(storm_id).upper}_CONE_latest.kmz"


def floater_url(storm_id: str | None = None, product: str | None = None) -> str:
    """The NESDIS floater directory: all storms, one storm's products, or one product's files."""
    if storm_id is None:
        return f"{FLOATER_BASE}/"
    base = f"{FLOATER_BASE}/{parse_storm_id(storm_id).upper}/"
    return base if product is None else f"{base}{quote(product)}/"


# ---- staleness ----------------------------------------------------------------------------------------------------


def text_is_current(storm: Storm, ref: ProductRef | None, *, storm_id: str | None, adv_num: AdvNum | None) -> bool:
    """True when a parsed text product belongs to this storm at the advisory CurrentStorms.json lists for it.

    tgftp and the NHC `.shtml` pages keep a finished storm's last advisory under the same bin, so text is applied only
    when the storm id and the advisory number both match. `ref` is the storm's reference for this product (for
    example `storm.public_advisory`); without one the storm's newest advisory number is used. Intermediate advisories
    differ by product (the public advisory can be 30A while the forecast advisory is 30), which is why the product's
    own reference is compared. A product with no advisory number cannot be confirmed and is treated as stale.
    """
    if storm_id is not None and storm_id.lower() != storm.id:
        return False
    expected = ref.adv_num if ref is not None and ref.adv_num is not None else storm.adv_num
    return adv_num is not None and expected is not None and adv_num == expected
