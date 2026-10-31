"""Record real NOAA storm payloads into tests/fixtures/nhc and tests/fixtures/gis.

Two ways in:

    python scripts/record_fixtures.py record [--group NAME ...] [--force] [--list]
        Fetch the committed fixture set: the recipes below. A recipe whose file already exists is skipped unless
        --force is given. Groups: erin, ptc, live, gtwo, graphics.

    python scripts/record_fixtures.py storm al052025 --adv 30 --adv 46 [--name erin] [--force]
        Record one storm's products from the NHC archive for the given advisories: forecast/advisory, public advisory,
        discussion and wind probabilities as text, the 5day and fcst GIS zips, the final b-deck and the best track zip.

Every file written is listed in tests/fixtures/nhc/sources.json with its URL, fetch time and SHA-256, next to the
hand-built files (which are marked as such). Requests go out one at a time, half a second apart, with the eyewall
User-Agent. The `live` group reads whatever NOAA is serving today: the last-advisory files in each product bin belong to
the most recent storm to use that bin, so the file names below (fay_039, nolo_057...) name what was served when they
were recorded. Saved payloads are never edited; fixtures/** is -text in .gitattributes so they stay byte for byte.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from eyewall.models.storm import AdvNum
from eyewall.net import FetchError, fetch_bytes, new_client
from eyewall.providers.nhc import ids

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
MANIFEST = FIXTURES / "nhc" / "sources.json"
DELAY_SECONDS = 0.5

_PRE = re.compile(r"<pre[^>]*>(.*?)</pre>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Recipe:
    """One fixture: where it lands (relative to tests/fixtures), where it comes from, and how to turn it into a file.

    transform: `raw` keeps the bytes; `pre` takes the product text out of an NHC archive page; `two:AT|EP|CP` takes one
    English outlook out of a graphical outlook archive page; `api-product` fetches the newest product named in an
    api.weather.gov product list and writes that to `path` (the list itself goes to `list_path`).
    """

    path: str
    url: str
    group: str
    transform: str = "raw"
    list_path: str | None = None
    note: str = ""


def _pre_text(page: bytes) -> bytes:
    blocks = _PRE.findall(page.decode("utf-8", errors="replace"))
    if not blocks:
        raise ValueError("no <pre> block in the page")
    text = html.unescape(_TAG.sub("", _BR.sub("\n", blocks[0])))
    return (text.strip("\n").replace("\r\n", "\n") + "\n").encode("utf-8")


def _two_text(page: bytes, code: str) -> bytes:
    """The English TWO for AT, EP or CP from a graphical outlook archive page (the Spanish ones are TWOS..)."""
    for block in _PRE.findall(page.decode("utf-8", errors="replace")):
        text = html.unescape(_TAG.sub("", _BR.sub("\n", block))).strip("\n")
        first = text.splitlines()[0] if text else ""
        if re.fullmatch(rf"ZCZC \w*TWO{code} ALL", first.strip()):
            return (text.replace("\r\n", "\n") + "\n").encode("utf-8")
    raise ValueError(f"no English TWO{code} block in the page")


def storm_recipes(storm_id: str, name: str, advisories: list[AdvNum], group: str) -> list[Recipe]:
    """Archive recipes for one storm: text products and GIS per advisory, plus the b-deck and best track."""
    recipes: list[Recipe] = []
    for adv in advisories:
        tag = f"{name}_{ids.format_adv_num(adv)}"
        for kind, folder in (("fstadv", "tcm"), ("public", "tcp"), ("discus", "tcd"), ("wndprb", "pws")):
            recipes.append(
                Recipe(f"nhc/{folder}/{tag}.txt", ids.archive_product_url(kind, storm_id, adv), group, "pre")
            )
        for layer in ("5day", "fcst"):
            recipes.append(
                Recipe(
                    f"gis/{name}_{layer}_{ids.format_adv_num(adv)}.zip",
                    ids.forecast_zip_url(storm_id, adv, layer),
                    group,
                )
            )
    recipes.append(Recipe(f"nhc/atcf/{ids.bdeck_name(storm_id)}.gz", ids.bdeck_archive_url(storm_id), group))
    recipes.append(Recipe(f"gis/{name}_best_track.zip", ids.best_track_zip_url(storm_id), group))
    return recipes


def _tgftp(kind: ids.ProductKind, bin_name: str) -> str:
    return ids.tgftp_url(kind, ids.parse_bin(bin_name))


def committed_recipes() -> list[Recipe]:
    """The fixture set the tests are written against."""
    erin = storm_recipes("al052025", "erin", [AdvNum(30)], "erin")
    # Erin: advisory 30 above, plus the late post-tropical advisory (text only) and an intermediate zip.
    erin += [
        Recipe("nhc/tcm/erin_046.txt", ids.archive_product_url("fstadv", "al052025", AdvNum(46)), "erin", "pre"),
        Recipe("gis/erin_5day_030A.zip", ids.forecast_zip_url("al052025", AdvNum(30, "A")), "erin"),
    ]
    ptc = [
        Recipe("nhc/tcm/ptc08_001.txt", ids.archive_product_url("fstadv", "al082024", AdvNum(1)), "ptc", "pre"),
        Recipe("nhc/tcp/ptc08_001.txt", ids.archive_product_url("public", "al082024", AdvNum(1)), "ptc", "pre"),
    ]
    live = [
        Recipe("nhc/current/empty.json", ids.CURRENT_STORMS_URL, "live"),
        # Last advisories left in the product bins (post-tropical, remnants, dissipated, the dateline, no radii).
        Recipe("nhc/tcm/fay_039.txt", _tgftp(ids.ProductKind.TCM, "AT1"), "live"),
        Recipe("nhc/tcm/josephine_005.txt", _tgftp(ids.ProductKind.TCM, "AT5"), "live"),
        Recipe("nhc/tcm/nolo_057.txt", _tgftp(ids.ProductKind.TCM, "CP2"), "live"),
        Recipe("nhc/tcm/olana_007.txt", _tgftp(ids.ProductKind.TCM, "CP3"), "live"),
        Recipe("nhc/tcm/vance_035.txt", _tgftp(ids.ProductKind.TCM, "EP2"), "live"),
        Recipe("nhc/tcp/fay_039.txt", _tgftp(ids.ProductKind.TCP, "AT1"), "live"),
        Recipe("nhc/tcp/isaias_015.txt", _tgftp(ids.ProductKind.TCP, "AT4"), "live"),
        Recipe("nhc/tcp/nolo_057.txt", _tgftp(ids.ProductKind.TCP, "CP2"), "live"),
        Recipe("nhc/tcd/fay_039.txt", _tgftp(ids.ProductKind.TCD, "AT1"), "live"),
        Recipe("nhc/tcd/nolo_057.txt", _tgftp(ids.ProductKind.TCD, "CP2"), "live"),
        Recipe("nhc/pws/fay_039.txt", _tgftp(ids.ProductKind.PWS, "AT1"), "live"),
        Recipe("nhc/pws/nolo_057.txt", _tgftp(ids.ProductKind.PWS, "CP2"), "live"),
        Recipe("nhc/two/at_20261031.txt", ids.outlook_url(ids.Basin.AL), "live"),
        Recipe("nhc/two/ep_20261031.txt", ids.outlook_url(ids.Basin.EP), "live"),
        Recipe("nhc/two/cp_20261031.txt", ids.outlook_url(ids.Basin.CP), "live"),
        Recipe("nhc/atcf/bal062026.dat", ids.bdeck_url("al062026"), "live"),
        Recipe("nhc/atcf/bcp032026.dat", ids.bdeck_url("cp032026"), "live"),
        Recipe("nhc/atcf/bep222026.dat", ids.bdeck_url("ep222026"), "live"),
        Recipe("nhc/atcf/btk_index.html", ids.BTK_INDEX_URL, "live"),
        Recipe(
            "nhc/api/alerts_active_none.json",
            ids.alerts_url() + "?event=" + ",".join(e.replace(" ", "%20") for e in ids.ALERT_EVENTS),
            "live",
        ),
        # Not tropical, but real api.weather.gov alerts: the shape the parser must read once a storm threatens land.
        Recipe(
            "nhc/api/alerts_real_shape.json",
            ids.alerts_url() + "?event=Freeze%20Warning,Frost%20Advisory",
            "live",
        ),
        Recipe(
            "nhc/api/product_two_at.json",
            ids.api_products_url(ids.ProductKind.TWO, "AT"),
            "live",
            "api-product",
            "nhc/api/products_two_at.json",
        ),
        Recipe("nhc/api/products_tcm_ep2.json", ids.api_products_url(ids.ProductKind.TCM, "EP2"), "live"),
        Recipe("gis/gtwo_20261031.zip", ids.GTWO_ZIP_URL, "live"),
        Recipe("gis/nolo_5day_057.zip", ids.forecast_zip_url("ep152026", AdvNum(57)), "live"),
        Recipe("gis/nolo_fcst_057.zip", ids.forecast_zip_url("ep152026", AdvNum(57), "fcst"), "live"),
        Recipe("gis/fay_5day_latest.zip", ids.forecast_zip_url("al062026", None), "live"),
    ]
    gtwo = [
        Recipe("gis/gtwo_20250919.zip", ids.gtwo_archive_zip_url("atl", "202509190600"), "gtwo"),
        Recipe("gis/gtwo_20250926.zip", ids.gtwo_archive_zip_url("atl", "202509260600"), "gtwo"),
    ]
    for code, label in (("AT", "at"), ("EP", "ep"), ("CP", "cp")):
        page = "https://www.nhc.noaa.gov/archive/xgtwo/gtwo_archive.php?basin=atl&fdays=7&current_issuance=202609100600"
        gtwo.append(Recipe(f"nhc/two/{label}_20260910.txt", page, "gtwo", f"two:{code}"))
    graphics = [
        Recipe("nhc/graphics/landing_at1_quiet.html", ids.graphics_landing_url(ids.parse_bin("AT1")), "graphics"),
        Recipe(
            "nhc/graphics/erin_cone_archive.html",
            "https://www.nhc.noaa.gov/archive/2025/ERIN_graphics.php?product=5day_cone_with_line_and_wind",
            "graphics",
        ),
        Recipe("nhc/graphics/floater_root.html", ids.floater_url(), "graphics"),
        Recipe("nhc/graphics/floater_cp032026.html", ids.floater_url("cp032026"), "graphics"),
        Recipe("nhc/graphics/floater_cp032026_geocolor.html", ids.floater_url("cp032026", "GEOCOLOR"), "graphics"),
    ]
    return erin + ptc + live + gtwo + graphics


# Hand-built fixtures: files that are not recordings, with the reason. They are written into the manifest too.
HAND_BUILT: dict[str, str] = {
    "nhc/two/at_special_20261031.txt": (
        "the routine at_20261031.txt with only the heading changed to 'Special Tropical Weather Outlook'. NHC issues "
        "specials under the same product header into the same tgftp file; none was available to record."
    ),
    "nhc/current/populated.json": (
        "hand-built from NHC_JSON_Sample.json and edited to the live shape: lowercase ids, string intensity and "
        "pressure, latitudeNumeric/longitudeNumeric, mph movement. Holds Erin (AT5), a potential tropical cyclone, "
        "a post-tropical storm and an ep id in a CP bin. No active storm exists to record from."
    ),
    "nhc/api/alerts_populated.json": (
        "hand-built in the api.weather.gov alert feature shape (CAP fields, SAME/UGC geocodes, polygon geometry). "
        "The alerts endpoint only serves active alerts and none were active."
    ),
    "nhc/graphics/landing_active_modelled.html": (
        "hand-built from the NHC landing page layout: image and link patterns are the ones documented in "
        "docs/data-sources.md and are confirmed during the first live storm."
    ),
}


def _load_manifest() -> dict[str, dict[str, str]]:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {}


def _save_manifest(manifest: dict[str, dict[str, str]]) -> None:
    for path, note in HAND_BUILT.items():
        manifest.setdefault(path, {"source": "hand-built", "note": note})
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    # Bytes, not write_text: Windows would turn the newlines into CRLF and fixtures are never normalised.
    MANIFEST.write_bytes((json.dumps(dict(sorted(manifest.items())), indent=2) + "\n").encode("utf-8"))


def _write(manifest: dict[str, dict[str, str]], path: str, url: str, body: bytes) -> None:
    target = FIXTURES / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    manifest[path] = {
        "source": url,
        "recorded": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sha256": hashlib.sha256(body).hexdigest(),
    }
    print(f"  wrote {path} ({len(body)} bytes)")


async def _run(recipes: list[Recipe], force: bool) -> int:
    manifest = _load_manifest()
    failures = 0
    pages: dict[str, bytes] = {}  # one page can hold several fixtures (the three outlooks), so fetch it once
    async with new_client() as client:
        for recipe in recipes:
            if (FIXTURES / recipe.path).exists() and not force:
                print(f"  skip {recipe.path} (exists)")
                continue
            try:
                if recipe.url not in pages:
                    pages[recipe.url] = (await fetch_bytes(client, recipe.url)).body
                    await asyncio.sleep(DELAY_SECONDS)
                body = pages[recipe.url]
                if recipe.transform == "pre":
                    body = _pre_text(body)
                elif recipe.transform.startswith("two:"):
                    body = _two_text(body, recipe.transform.split(":", 1)[1])
                elif recipe.transform == "api-product":
                    assert recipe.list_path is not None
                    _write(manifest, recipe.list_path, recipe.url, body)
                    newest = json.loads(body)["@graph"][0]["id"]
                    await asyncio.sleep(DELAY_SECONDS)
                    product_url = ids.api_product_url(newest)
                    body = (await fetch_bytes(client, product_url)).body
                    _write(manifest, recipe.path, product_url, body)
                    await asyncio.sleep(DELAY_SECONDS)
                    continue
                _write(manifest, recipe.path, recipe.url, body)
            except (FetchError, ValueError, KeyError, IndexError) as exc:
                failures += 1
                print(f"  FAILED {recipe.path}: {exc}", file=sys.stderr)
    _save_manifest(manifest)
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    record = sub.add_parser("record", help="fetch the committed fixture set")
    record.add_argument("--group", action="append", help="only this group (repeatable)")
    record.add_argument("--force", action="store_true", help="overwrite files that already exist")
    record.add_argument("--list", action="store_true", help="print the recipes and exit")
    storm = sub.add_parser("storm", help="record one storm's archive products")
    storm.add_argument("storm_id", help="for example al052025")
    storm.add_argument("--adv", action="append", required=True, help="advisory number such as 30 or 30A (repeatable)")
    storm.add_argument("--name", help="file name prefix (default: the storm id)")
    storm.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "record":
        recipes = [r for r in committed_recipes() if not args.group or r.group in args.group]
        if args.list:
            for recipe in recipes:
                print(f"{recipe.group:9} {recipe.path:48} {recipe.url}")
            return 0
        return 1 if asyncio.run(_run(recipes, args.force)) else 0

    advisories = [a for a in (ids.parse_adv_num(text) for text in args.adv) if a is not None]
    if len(advisories) != len(args.adv):
        parser.error("--adv takes advisory numbers such as 30 or 30A")
    name = args.name or ids.normalize_storm_id(args.storm_id)
    recipes = storm_recipes(args.storm_id, name, advisories, "storm")
    return 1 if asyncio.run(_run(recipes, args.force)) else 0


if __name__ == "__main__":
    sys.exit(main())
