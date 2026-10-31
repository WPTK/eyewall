"""The gallery's list: order, titles, link-only files and the satellite stills and loops."""

from __future__ import annotations

from datetime import UTC, datetime

from eyewall.models.graphics import FloaterProduct, GraphicKind, GraphicLink
from eyewall.models.storm import AdvNum
from eyewall.state.store import StormState
from eyewall.ui.gallery import build_items
from tests.state_support import make_storm

ADV = AdvNum(38)


def link(kind, product, media="png", **kw):
    return GraphicLink(kind, product, f"https://www.nhc.noaa.gov/{product}.{media}", media, ADV, **kw)


def state(*links, satellite=()):
    return StormState(make_storm("38"), graphics=tuple(links), satellite=tuple(satellite))


def titles(items):
    return [i.title for i in items]


def test_forecast_graphics_come_in_reading_order_with_the_thresholds_sorted():
    items = build_items(
        state(
            link(GraphicKind.SURGE_PEAK, "peak_surge"),
            link(GraphicKind.WIND_PROBABILITY, "wsp64", threshold_kt=64),
            link(GraphicKind.CONE, "5day_cone_with_line_and_wind", days=5),
            link(GraphicKind.WIND_PROBABILITY, "wsp34", threshold_kt=34),
            link(GraphicKind.ARRIVAL_MOST_LIKELY, "most_likely_toa_34", threshold_kt=34),
            link(GraphicKind.WIND_PROBABILITY, "wsp50", threshold_kt=50),
            link(GraphicKind.ARRIVAL_EARLIEST, "earliest_reasonable_toa_34", threshold_kt=34),
            link(GraphicKind.SURGE_WATCH_WARNING, "watch_warning"),
        )
    )
    assert titles(items) == [
        "Cone, 5 day",
        "Wind probability 34 kt",
        "Wind probability 50 kt",
        "Wind probability 64 kt",
        "Earliest arrival of winds (34 kt)",
        "Most likely arrival of winds (34 kt)",
        "Storm surge watch and warning",
        "Peak storm surge",
    ]
    assert items[0].cone and not items[1].cone
    assert items[0].version == str(ADV)


def test_kmz_files_are_listed_as_link_only_and_other_kinds_are_left_out():
    items = build_items(
        state(
            link(GraphicKind.CONE, "5day_cone", "png", days=5),
            link(GraphicKind.CONE, "5day_cone", "kmz", days=5),
            link(GraphicKind.OTHER, "banner"),
            link(GraphicKind.CONE, "5day_cone", "png", days=5),  # the same file twice
        )
    )
    assert titles(items) == ["Cone, 5 day", "Cone, 5 day (KMZ, link only)"]
    assert [i.viewable for i in items] == [True, False]


def test_two_cones_with_one_title_are_told_apart_by_product():
    items = build_items(
        state(
            link(GraphicKind.CONE, "5day_cone_with_line_and_wind", days=5),
            link(GraphicKind.CONE, "5day_cone_no_line_and_wind", days=5),
        )
    )
    assert len(set(titles(items))) == 2
    assert titles(items)[1].endswith("[5day_cone_with_line_and_wind]")


def test_satellite_stills_and_loops_follow_the_forecast_graphics():
    when = datetime(2026, 10, 31, 15, 0, tzinfo=UTC)
    geocolor = FloaterProduct(
        "al102026", "GEOCOLOR", "https://n/", still_url="https://n/s.jpg", still_time=when, loop_url="https://n/l.gif"
    )
    airmass = FloaterProduct("al102026", "AirMass", "https://n/", latest_url="https://n/latest.jpg")
    items = build_items(
        state(link(GraphicKind.CONE, "cone", days=5), satellite=(geocolor,)),
        {"AirMass": airmass, "13": None},
    )
    assert titles(items) == ["Cone, 5 day", "GEOCOLOR still", "GEOCOLOR loop", "Air mass still"]
    still, loop = items[1], items[2]
    assert (still.url, still.version, still.loop) == ("https://n/s.jpg", "2026-10-31 15:00Z", False)
    assert (loop.media, loop.loop) == ("gif", True)
    assert items[3].url.endswith("latest.jpg") and items[3].version == "latest"


def test_a_storm_with_nothing_has_an_empty_gallery():
    assert build_items(state()) == []
