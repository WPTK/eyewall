from collections import Counter
from datetime import UTC, datetime

from eyewall.models.graphics import GraphicKind
from eyewall.models.storm import AdvNum
from eyewall.providers.nhc.graphics import (
    parse_floater_listing,
    parse_floater_products,
    parse_floater_storms,
    parse_graphics_page,
)
from tests.nhc_fixtures import nhc_bytes

LANDING = "https://www.nhc.noaa.gov/graphics_at5.shtml"
ARCHIVE = "https://www.nhc.noaa.gov/archive/2025/ERIN_graphics.php?product=5day_cone_with_line_and_wind"


def test_quiet_day_landing_page_has_no_storm_graphics():
    # The recorded live page for AT1: a "not ready" placeholder and site chrome only.
    assert (
        parse_graphics_page(nhc_bytes("graphics/landing_at1_quiet.html"), "https://www.nhc.noaa.gov/graphics_at1.shtml")
        == ()
    )


def test_erin_archive_cone_page_lists_one_image_per_advisory():
    links = parse_graphics_page(nhc_bytes("graphics/erin_cone_archive.html"), ARCHIVE)
    assert len(links) == 76
    assert Counter(link.kind for link in links) == {GraphicKind.CONE: 76}
    assert {link.product for link in links} == {"5day_cone_with_line_and_wind"}
    assert {link.media for link in links} == {"png"}
    assert {link.days for link in links} == {5}
    first = links[0]
    assert (
        first.url
        == "https://www.nhc.noaa.gov/archive/2025/graphics/AL052025/AL052025_5day_cone_with_line_and_wind_1.png"
    )
    assert first.adv_num == AdvNum(1)
    advisories = {link.adv_num for link in links}
    assert AdvNum(14, "A") in advisories  # intermediate advisories have their own image
    assert AdvNum(46) in advisories
    assert len(links) == len({link.url for link in links})


def test_modelled_landing_page_is_classified_by_product_name():
    # Hand-built from the documented URL patterns; confirmed during the first live storm.
    links = parse_graphics_page(nhc_bytes("graphics/landing_active_modelled.html"), LANDING)
    kinds = [(link.kind, link.threshold_kt, link.media) for link in links]
    assert kinds == [
        (GraphicKind.CONE, None, "png"),
        (GraphicKind.CONE, None, "png"),
        (GraphicKind.CONE, None, "kmz"),
        (GraphicKind.WIND_PROBABILITY, 34, "png"),
        (GraphicKind.WIND_PROBABILITY, 50, "png"),
        (GraphicKind.WIND_PROBABILITY, 64, "png"),
        (GraphicKind.ARRIVAL_EARLIEST, 34, "png"),
        (GraphicKind.ARRIVAL_MOST_LIKELY, 34, "png"),
        (GraphicKind.SURGE_PEAK, None, "png"),
        (GraphicKind.CURRENT_WIND, None, "png"),
    ]
    refresh = links[1]
    assert refresh.url == (
        "https://www.nhc.noaa.gov/storm_graphics/AT05/refresh/AL052025_5day_cone_with_line_and_wind+png/"
        "210014_5day_cone_with_line_and_wind.png"
    )
    assert refresh.product == "5day_cone_with_line_and_wind"  # the time stamp prefix is not part of the product
    assert refresh.days == 5
    assert refresh.adv_num is None
    # Site chrome, the placeholder and the spacer gif are left out.
    assert not any("logo" in link.url or "notready" in link.url or "skipgraphic" in link.url for link in links)


def test_threshold_numbers_are_not_mistaken_for_advisory_numbers():
    html = '<img src="/storm_graphics/AT05/AL052025_earliest_reasonable_toa_34.png"><img src="/storm_graphics/AT05/AL052025_wind_probs_50_F120.png">'
    first, second = parse_graphics_page(html, LANDING)
    assert (first.kind, first.threshold_kt, first.adv_num, first.product) == (
        GraphicKind.ARRIVAL_EARLIEST,
        34,
        None,
        "earliest_reasonable_toa_34",
    )
    assert (second.kind, second.threshold_kt, second.adv_num) == (GraphicKind.WIND_PROBABILITY, 50, None)


def test_links_resolve_against_the_page_url_and_deduplicate():
    html = (
        '<a href="/storm_graphics/AT05/AL052025_key_messages.png">k</a>'
        '<img src="https://www.nhc.noaa.gov/storm_graphics/AT05/AL052025_key_messages.png">'
        '<img src="rain/AL052025_rainqpf.png">'
    )
    links = parse_graphics_page(html, "https://www.nhc.noaa.gov/storm_graphics/graphics_at5.shtml")
    assert [link.kind for link in links] == [GraphicKind.KEY_MESSAGES, GraphicKind.RAINFALL]
    assert links[1].url == "https://www.nhc.noaa.gov/storm_graphics/rain/AL052025_rainqpf.png"


def test_a_page_with_no_images_gives_nothing():
    assert parse_graphics_page("", LANDING) == ()
    assert parse_graphics_page(b"<html><body>Hello</body></html>", LANDING) == ()


# ---- NESDIS floater -----------------------------------------------------------------------------------------------


def test_floater_root_lists_storm_directories():
    storms = parse_floater_storms(nhc_bytes("graphics/floater_root.html"))
    assert len(storms) == 35
    assert storms[0] == "AL012026"
    assert "CP032026" in storms
    assert "2024Eclipse" not in storms


def test_floater_storm_directory_lists_products():
    products = parse_floater_products(nhc_bytes("graphics/floater_cp032026.html"))
    assert products == (
        *(f"{n:02d}" for n in range(1, 17)),
        "AirMass",
        "DayConvection",
        "DayNightCloudMicroCombo",
        "EXTENT3",
        "GEOCOLOR",
        "Sandwich",
    )


def test_floater_product_listing_gives_the_newest_still_and_the_loop():
    product = parse_floater_listing(nhc_bytes("graphics/floater_cp032026_geocolor.html"), "CP032026", "GEOCOLOR")
    base = "https://cdn.star.nesdis.noaa.gov/FLOATER/data/CP032026/GEOCOLOR/"
    assert product.storm_id == "cp032026"
    assert product.product == "GEOCOLOR"
    assert product.base_url == base
    assert product.still_url == base + "20263001050_GOES18-ABI-FL-GEOCOLOR-CP032026-1000x1000.jpg"
    assert product.still_time == datetime(2026, 10, 27, 10, 50, tzinfo=UTC)  # day 300 of 2026
    assert product.latest_url == base + "latest.jpg"
    assert product.loop_url == base + "CP032026-GEOCOLOR-1000x1000.gif"
    assert product.loop_start is None and product.loop_end is None  # the full loop has no range


def test_floater_loop_falls_back_to_the_newest_time_ranged_gif():
    html = (
        '<a href="20262981510-20262981540-ABI-CP032026-GEOCOLOR-1000x1000.gif">a</a>'
        '<a href="20262981510-20262982040-ABI-CP032026-GEOCOLOR-1000x1000.gif">b</a>'
        '<a href="20262981510_GOES18-ABI-FL-GEOCOLOR-CP032026-1000x1000.jpg">c</a>'
        '<a href="1000x1000.jpg">d</a>'
    )
    product = parse_floater_listing(html, "CP032026", "GEOCOLOR")
    assert product.loop_url.endswith("20262981510-20262982040-ABI-CP032026-GEOCOLOR-1000x1000.gif")
    assert product.loop_start == datetime(2026, 10, 25, 15, 10, tzinfo=UTC)
    assert product.loop_end == datetime(2026, 10, 25, 20, 40, tzinfo=UTC)
    assert product.latest_url.endswith("/1000x1000.jpg")
    assert product.still_time == datetime(2026, 10, 25, 15, 10, tzinfo=UTC)


def test_an_empty_floater_listing_has_no_urls():
    product = parse_floater_listing("<html></html>", "al052025", "GEOCOLOR")
    assert (product.still_url, product.latest_url, product.loop_url) == (None, None, None)


def test_absolute_links_to_other_hosts_are_ignored_and_http_noaa_links_are_upgraded():
    html = (
        '<img src="/storm_graphics/AT05/a_5day_cone_with_line_and_wind.png">'
        '<img src="https://evil.example/storm_graphics/AT05/x_5day_cone.png">'
        '<img src="//evil.example/storm_graphics/AT05/y_5day_cone.png">'
        '<img src="https://noaa.gov.evil.example/storm_graphics/AT05/z_5day_cone.png">'
        '<img src="http://www.nhc.noaa.gov/storm_graphics/AT05/w_5day_cone.png">'
    )
    urls = [link.url for link in parse_graphics_page(html, LANDING)]
    assert urls == [
        "https://www.nhc.noaa.gov/storm_graphics/AT05/a_5day_cone_with_line_and_wind.png",
        "https://www.nhc.noaa.gov/storm_graphics/AT05/w_5day_cone.png",
    ]


def test_odd_schemes_and_malformed_absolute_links_never_become_graphics():
    html = (
        '<img src="file:/etc/storm_graphics/x_5day_cone.png">'
        '<img src="http:/evil.com/storm_graphics/x_5day_cone.png">'
        '<img src="abcdefghij://evil.com/storm_graphics/x_5day_cone.png">'
        '<img src="/storm_graphics/AT05/ok_5day_cone.png">'
    )
    assert [link.url for link in parse_graphics_page(html, LANDING)] == [
        "https://www.nhc.noaa.gov/storm_graphics/AT05/ok_5day_cone.png"
    ]
