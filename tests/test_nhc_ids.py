from datetime import UTC, datetime

import pytest

from eyewall.models.storm import AdvNum, Basin
from eyewall.providers.nhc import ids
from eyewall.providers.nhc.ids import ProductKind
from eyewall.providers.nhc.times import parse_header_time, parse_iso, resolve_day_time


def test_storm_ids_normalise_to_lower_case():
    assert ids.normalize_storm_id("AL052025") == "al052025"
    assert ids.normalize_storm_id(" ep152026 ") == "ep152026"
    parsed = ids.parse_storm_id("CP032026")
    assert (parsed.basin, parsed.number, parsed.year) == (Basin.CP, 3, 2026)
    assert parsed.upper == "CP032026"
    assert ids.parse_storm_id("al902026").is_invest
    assert not ids.parse_storm_id("al052026").is_invest


@pytest.mark.parametrize("text", ["", "al52025", "xx052025", "al05202", "AT5", "al052025x"])
def test_malformed_storm_ids_raise(text):
    with pytest.raises(ValueError):
        ids.normalize_storm_id(text)


def test_advisory_numbers_parse_the_intermediate_suffix():
    assert ids.parse_adv_num("018a") == AdvNum(18, "A")
    assert ids.parse_adv_num("030") == AdvNum(30)
    assert ids.parse_adv_num(5) == AdvNum(5)
    assert ids.parse_adv_num(" 7 ") == AdvNum(7)
    assert ids.parse_adv_num("18a").intermediate
    assert not ids.parse_adv_num("18").intermediate
    assert str(AdvNum(18, "A")) == "18A"


@pytest.mark.parametrize("value", [None, "", "x", "A18", True, 3.5, -1, "1.5"])
def test_things_that_are_not_advisory_numbers_come_back_none(value):
    assert ids.parse_adv_num(value) is None


def test_advisory_numbers_order_with_intermediates_after_their_advisory():
    assert AdvNum(18) < AdvNum(18, "A") < AdvNum(19)
    assert ids.format_adv_num(AdvNum(30, "A")) == "030A"
    assert ids.format_adv_num(AdvNum(7), width=2) == "07"


def test_bins_parse_and_map_to_basins():
    assert ids.parse_bin("at1") == ids.Bin("AT", 1)
    assert ids.parse_bin("AT5").basin is Basin.AL
    assert ids.parse_bin("cp2").basin is Basin.CP
    assert ids.parse_bin("EP4").name == "EP4"
    assert [b.name for b in ids.bins_for(Basin.AL)] == ["AT1", "AT2", "AT3", "AT4", "AT5"]
    assert [b.name for b in ids.bins_for(Basin.CP)] == ["CP1", "CP2", "CP3", "CP4", "CP5"]
    for bad in ("AT6", "AT0", "KNHC", "AL1", ""):
        with pytest.raises(ValueError):
            ids.parse_bin(bad)


@pytest.mark.parametrize(
    ("kind", "bin_name", "path"),
    [
        (ProductKind.TCM, "AT1", "wt/wtnt21.knhc.tcm.at1.txt"),
        (ProductKind.TCM, "AT5", "wt/wtnt25.knhc.tcm.at5.txt"),
        (ProductKind.TCM, "EP2", "wt/wtpz22.knhc.tcm.ep2.txt"),
        (ProductKind.TCM, "CP2", "wt/wtpa22.phfo.tcm.cp2.txt"),
        (ProductKind.TCP, "AT4", "wt/wtnt34.knhc.tcp.at4.txt"),
        (ProductKind.TCP, "CP2", "wt/wtpa32.phfo.tcp.cp2.txt"),
        (ProductKind.TCD, "EP1", "wt/wtpz41.knhc.tcd.ep1.txt"),
        (ProductKind.TCD, "CP5", "wt/wtpa45.phfo.tcd.cp5.txt"),
        (ProductKind.TCU, "AT3", "wt/wtnt63.knhc.tcu.at3.txt"),
        (ProductKind.PWS, "AT1", "fo/font11.knhc.pws.at1.txt"),
        (ProductKind.PWS, "EP3", "fo/fopz13.knhc.pws.ep3.txt"),
        (ProductKind.PWS, "CP2", "fo/fopa12.phfo.pws.cp2.txt"),
    ],
)
def test_tgftp_urls_follow_the_observed_directory_names(kind, bin_name, path):
    assert ids.tgftp_url(kind, ids.parse_bin(bin_name)) == f"https://tgftp.nws.noaa.gov/data/raw/{path}"


def test_outlook_products_are_per_basin():
    assert ids.outlook_url(Basin.AL).endswith("/ab/abnt20.knhc.two.at.txt")
    assert ids.outlook_url(Basin.EP).endswith("/ab/abpz20.knhc.two.ep.txt")
    assert ids.outlook_url(Basin.CP).endswith("/ac/acpn50.phfo.two.cp.txt")
    assert [ids.outlook_location(b) for b in Basin] == ["AT", "EP", "CP"]
    with pytest.raises(ValueError):
        ids.tgftp_url(ProductKind.TWO, ids.parse_bin("AT1"))


def test_api_urls_use_the_bin_never_the_office():
    assert ids.api_products_url(ProductKind.TCM, "ep2") == "https://api.weather.gov/products/types/TCM/locations/EP2"
    assert ids.api_products_url(ProductKind.TWO, "AT").endswith("/types/TWO/locations/AT")
    assert ids.api_product_url("abc-123") == "https://api.weather.gov/products/abc-123"
    assert ids.alerts_url() == "https://api.weather.gov/alerts/active"
    events = ids.alerts_params()["event"].split(",")
    assert "Hurricane Warning" in events
    assert "Storm Surge Watch" in events
    assert len(events) == 9


def test_atcf_urls_cover_the_cp_basin_and_the_archive():
    assert ids.bdeck_name("AL052025") == "bal052025.dat"
    assert ids.bdeck_url("cp032026") == "https://ftp.nhc.noaa.gov/atcf/btk/bcp032026.dat"
    assert ids.bdeck_archive_url("al052025") == "https://ftp.nhc.noaa.gov/atcf/archive/2025/bal052025.dat.gz"
    assert ids.BTK_INDEX_URL == "https://ftp.nhc.noaa.gov/atcf/btk/"


def test_gis_and_archive_urls():
    assert ids.forecast_zip_url("al052025", AdvNum(30)) == (
        "https://www.nhc.noaa.gov/gis/forecast/archive/al052025_5day_030.zip"
    )
    assert ids.forecast_zip_url("al052025", AdvNum(30, "A")).endswith("_5day_030A.zip")
    assert ids.forecast_zip_url("al052025", AdvNum(30), "fcst").endswith("_fcst_030.zip")
    assert ids.forecast_zip_url("al052025", None).endswith("_5day_latest.zip")
    assert ids.best_track_zip_url("AL052025") == "https://www.nhc.noaa.gov/gis/best_track/al052025_best_track.zip"
    assert ids.gtwo_archive_zip_url("atl", "202509190600").endswith("/xgtwo/atl/202509190600/gtwo_shapefiles.zip")
    assert ids.archive_product_url("fstadv", "al052025", AdvNum(30)) == (
        "https://www.nhc.noaa.gov/archive/2025/al05/al052025.fstadv.030.shtml"
    )
    assert ids.archive_product_url("discus", "ep152026", AdvNum(57)).endswith("/2026/ep15/ep152026.discus.057.shtml")
    with pytest.raises(ValueError):
        ids.archive_product_url("nope", "al052025", AdvNum(1))


def test_graphics_and_floater_urls():
    assert ids.graphics_landing_url(ids.parse_bin("AT1")) == "https://www.nhc.noaa.gov/graphics_at1.shtml"
    assert ids.cone_kmz_url("al052025").endswith("/storm_graphics/api/AL052025_CONE_latest.kmz")
    assert ids.floater_url() == "https://cdn.star.nesdis.noaa.gov/FLOATER/data/"
    assert ids.floater_url("al052025").endswith("/FLOATER/data/AL052025/")
    assert ids.floater_url("al052025", "GEOCOLOR").endswith("/FLOATER/data/AL052025/GEOCOLOR/")


# ---- times --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("500 PM EDT Mon Aug 18 2025", datetime(2025, 8, 18, 21, 0, tzinfo=UTC)),
        ("2100 UTC MON AUG 18 2025", datetime(2025, 8, 18, 21, 0, tzinfo=UTC)),
        ("1100 PM PDT Wed Sep 9 2026", datetime(2026, 9, 10, 6, 0, tzinfo=UTC)),
        ("800 PM HST Fri Oct 30 2026", datetime(2026, 10, 31, 6, 0, tzinfo=UTC)),
        ("1200 AM EDT Sat Oct 31 2026", datetime(2026, 10, 31, 4, 0, tzinfo=UTC)),
        ("1200 PM EDT Sat Oct 31 2026", datetime(2026, 10, 31, 16, 0, tzinfo=UTC)),
        ("1100 AM HST Sun Oct 04 2026", datetime(2026, 10, 4, 21, 0, tzinfo=UTC)),
        ("500 PM AST Tue Sep 29 2026", datetime(2026, 9, 29, 21, 0, tzinfo=UTC)),
        ("0300 UTC TUE OCT 27 2026", datetime(2026, 10, 27, 3, 0, tzinfo=UTC)),
    ],
)
def test_header_times_convert_to_utc(text, expected):
    assert parse_header_time(text) == expected


@pytest.mark.parametrize("text", ["", "no time here", "500 PM XYZ Mon Aug 18 2025", "500 PM EDT Mon Foo 18 2025"])
def test_unknown_header_times_come_back_none(text):
    assert parse_header_time(text) is None


def test_day_and_hour_resolve_to_the_nearest_month():
    advisory = datetime(2025, 8, 31, 21, 0, tzinfo=UTC)
    assert resolve_day_time(1, 6, 0, advisory) == datetime(2025, 9, 1, 6, 0, tzinfo=UTC)
    assert resolve_day_time(31, 18, 0, advisory) == datetime(2025, 8, 31, 18, 0, tzinfo=UTC)
    january = datetime(2026, 1, 1, 3, 0, tzinfo=UTC)
    assert resolve_day_time(31, 18, 0, january) == datetime(2025, 12, 31, 18, 0, tzinfo=UTC)
    december = datetime(2025, 12, 30, 21, 0, tzinfo=UTC)
    assert resolve_day_time(2, 6, 0, december) == datetime(2026, 1, 2, 6, 0, tzinfo=UTC)


def test_day_that_does_not_exist_in_a_month_is_skipped():
    # 31 September does not exist, so the nearest real 31st is in August.
    assert resolve_day_time(31, 12, 0, datetime(2025, 9, 1, 0, 0, tzinfo=UTC)) == datetime(
        2025, 8, 31, 12, 0, tzinfo=UTC
    )
    assert resolve_day_time(32, 0, 0, datetime(2025, 9, 1, tzinfo=UTC)) is None


def test_iso_timestamps_are_tolerated():
    assert parse_iso("2026-09-25T06:00:00.000Z") == datetime(2026, 9, 25, 6, 0, tzinfo=UTC)
    assert parse_iso("2025-08-18T21:00:00-04:00") == datetime(2025, 8, 19, 1, 0, tzinfo=UTC)
    assert parse_iso("2025-08-18T21:00:00") == datetime(2025, 8, 18, 21, 0, tzinfo=UTC)
    for bad in (None, "", "  ", "yesterday", 17):
        assert parse_iso(bad) is None
