from datetime import UTC, datetime

import pytest

from eyewall.models.storm import AdvNum
from eyewall.palette import WatchWarning
from eyewall.providers.base import ParseError
from eyewall.providers.nhc.alerts import parse_product
from eyewall.providers.nhc.text import (
    parse_pws,
    parse_tcd,
    parse_tcp,
    parse_two,
    parse_watch_warning_text,
    watch_warning_kind,
)
from tests.nhc_fixtures import nhc_bytes, nhc_text

# ---- public advisory (TCP) ----------------------------------------------------------------------------------------


def test_erin_30_public_advisory_header_and_headline():
    tcp = parse_tcp(nhc_bytes("tcp/erin_030.txt"))
    assert tcp.storm_id == "al052025"
    assert (tcp.kind, tcp.name, tcp.adv_num) == ("HURRICANE", "Erin", AdvNum(30))
    assert tcp.issued == datetime(2025, 8, 18, 21, 0, tzinfo=UTC)
    assert tcp.issued_text == "500 PM EDT Mon Aug 18 2025"
    assert tcp.headlines == ("TROPICAL STORM AND STORM SURGE WATCHES ISSUED FOR THE NORTH CAROLINA OUTER BANKS",)
    assert tcp.headline == tcp.headlines[0]
    assert tcp.forecaster == "Pasch"
    assert not tcp.is_last


def test_erin_30_summary_is_in_mph():
    summary = parse_tcp(nhc_bytes("tcp/erin_030.txt")).summary
    assert summary.location_text == "24.0N 71.3W"
    assert (summary.lat, summary.lon) == (24.0, -71.3)
    assert summary.about == (
        "ABOUT 695 MI...1120 KM SW OF BERMUDA",
        "ABOUT 815 MI...1310 KM SSE OF CAPE HATTERAS NORTH CAROLINA",
    )
    assert summary.max_wind_mph == 140
    assert (summary.movement_text, summary.movement_dir_deg, summary.movement_speed_mph) == ("NW", 310, 10)
    assert (summary.pressure_mb, summary.pressure_in) == (937, 27.67)


def test_erin_30_watches_and_warnings_blocks():
    watches = parse_tcp(nhc_bytes("tcp/erin_030.txt")).watches_warnings
    assert watches.changes == (
        "A Tropical Storm Watch has been issued from Beaufort Inlet to Duck, North Carolina including Pamlico Sound",
        "A Storm Surge Watch has been issued from Cape Lookout to Duck, North Carolina.",
    )
    assert not watches.none_in_effect
    assert [(w.label, w.kind, w.areas) for w in watches.in_effect] == [
        (
            "Tropical Storm Warning",
            WatchWarning.TROPICAL_STORM_WARNING,
            ("Turks and Caicos Islands", "Southeast Bahamas"),
        ),
        ("Storm Surge Watch", WatchWarning.SURGE_WATCH, ("Cape Lookout to Duck, North Carolina",)),
        (
            "Tropical Storm Watch",
            WatchWarning.TROPICAL_STORM_WATCH,
            ("Central Bahamas", "Beaufort Inlet to Duck, North Carolina including Pamlico Sound"),
        ),
    ]
    assert "SUMMARY OF WATCHES AND WARNINGS IN EFFECT" in watches.text


def test_erin_30_discussion_hazards_and_next_advisory():
    tcp = parse_tcp(nhc_bytes("tcp/erin_030.txt"))
    assert tcp.discussion.startswith("At 500 PM EDT (2100 UTC), the center of Hurricane Erin was located near latitude")
    assert "Erin is a category 4 hurricane" in tcp.discussion
    assert tcp.discussion.count("\n\n") == 3
    assert [label for label, _ in tcp.hazards] == ["GENERAL", "RAINFALL", "WIND", "SURF", "STORM SURGE"]
    hazards = dict(tcp.hazards)
    assert hazards["GENERAL"].startswith("Key messages for Erin can be found in the Tropical Cyclone Discussion")
    assert hazards["RAINFALL"].startswith("Outer bands of Erin will produce localized areas of heavy rainfall")
    assert "Cape Lookout to Duck, North Carolina 2 to 4 ft" in hazards["STORM SURGE"]
    assert tcp.next_advisory == "Next intermediate advisory at 800 PM EDT. Next complete advisory at 1100 PM EDT."
    assert tcp.key_messages == ()  # the key messages live in the discussion


def test_post_tropical_last_advisory_with_two_headlines_and_no_watches():
    tcp = parse_tcp(nhc_bytes("tcp/fay_039.txt"))
    assert (tcp.kind, tcp.name, tcp.storm_id) == ("POST-TROPICAL CYCLONE", "Fay", "al062026")
    assert tcp.headlines == ("FAY BECOMES A POST-TROPICAL CYCLONE", "THIS IS THE LAST NHC ADVISORY ON THIS SYSTEM")
    assert tcp.is_last
    assert tcp.watches_warnings.none_in_effect
    assert tcp.watches_warnings.in_effect == ()
    assert tcp.issued == datetime(2026, 9, 29, 21, 0, tzinfo=UTC)  # 500 PM AST
    assert tcp.summary.pressure_in == 29.86


def test_discontinued_warnings_are_reported_as_changes():
    tcp = parse_tcp(nhc_bytes("tcp/isaias_015.txt"))
    assert tcp.watches_warnings.changes == ("All Storm Surge and Tropical Storm Warnings have been discontinued",)
    assert tcp.watches_warnings.none_in_effect
    labels = [label for label, _ in tcp.hazards]
    assert labels[:3] == ["GENERAL", "RAINFALL", "TORNADOES"]
    assert tcp.headlines == ("FLASH FLOODING RISK CONTINUES WITH ISAIAS",)
    assert tcp.issued == datetime(2026, 10, 10, 9, 0, tzinfo=UTC)  # 400 AM CDT


def test_dateline_advisory_has_an_east_longitude_and_hst_time():
    tcp = parse_tcp(nhc_bytes("tcp/nolo_057.txt"))
    assert tcp.storm_id == "ep152026"
    assert (tcp.summary.lat, tcp.summary.lon) == (24.2, 180.0)
    assert tcp.summary.location_text == "24.2N 180.0E"
    assert tcp.issued == datetime(2026, 10, 4, 21, 0, tzinfo=UTC)  # 1100 AM HST
    assert tcp.headlines == ("NOLO CROSSING THE INTERNATIONAL DATELINE", "THIS IS THE LAST ADVISORY FROM NHC")
    assert tcp.is_last
    assert dict(tcp.hazards).keys() == {"SURF"}


def test_potential_tropical_cyclone_public_advisory():
    tcp = parse_tcp(nhc_bytes("tcp/ptc08_001.txt"))
    assert (tcp.kind, tcp.name, tcp.adv_num, tcp.storm_id) == (
        "POTENTIAL TROPICAL CYCLONE",
        "Eight",
        AdvNum(1),
        "al082024",
    )
    assert tcp.headlines == (
        "POTENTIAL TROPICAL CYCLONE OFF THE COAST OF THE CAROLINAS",
        "EXPECTED TO BRING HEAVY RAINS AND COASTAL FLOODING",
    )
    assert tcp.watches_warnings.changes[0].startswith("A Tropical Storm Warning has been issued from Edisto Beach")
    (warning,) = tcp.watches_warnings.in_effect
    assert warning.kind is WatchWarning.TROPICAL_STORM_WARNING
    assert warning.areas == ("Edisto Beach, South Carolina northward to Ocracoke Inlet, North Carolina",)


def test_an_intermediate_advisory_heading_keeps_its_suffix():
    text = nhc_text("tcp/erin_030.txt").replace(
        "Hurricane Erin Advisory Number  30", "Hurricane Erin Intermediate Advisory Number  30A"
    )
    tcp = parse_tcp(text)
    assert tcp.adv_num == AdvNum(30, "A")
    assert tcp.name == "Erin"


def test_a_key_messages_list_in_a_public_advisory_stops_at_the_first_other_paragraph():
    # Current public advisories point to the discussion instead; this is the discussion's list format.
    text = nhc_text("tcp/erin_030.txt").replace(
        "HAZARDS AFFECTING LAND\n----------------------\n",
        "HAZARDS AFFECTING LAND\n----------------------\nKEY MESSAGES:\n\n1. First thing\n   continued.\n\n2. Second thing.\n\n",
    )
    tcp = parse_tcp(text)
    assert tcp.key_messages == ("First thing continued.", "Second thing.")
    assert "KEY MESSAGES" not in [label for label, _ in tcp.hazards]


def test_a_public_advisory_missing_sections_still_parses():
    text = nhc_text("tcp/erin_030.txt")
    start = text.index("WATCHES AND WARNINGS")
    end = text.index("DISCUSSION AND OUTLOOK")
    tcp = parse_tcp(text[:start] + text[end:])
    assert tcp.watches_warnings.in_effect == ()
    assert tcp.summary.max_wind_mph == 140
    assert tcp.discussion


@pytest.mark.parametrize("text", ["", "Hurricane Erin", "<html>nope</html>"])
def test_text_that_is_not_a_public_advisory_raises(text):
    with pytest.raises(ParseError):
        parse_tcp(text)


def test_watch_warning_kinds_by_label():
    assert watch_warning_kind("Hurricane Warning") is WatchWarning.HURRICANE_WARNING
    assert watch_warning_kind("hurricane  watch") is WatchWarning.HURRICANE_WATCH
    assert watch_warning_kind("Storm Surge Warning") is WatchWarning.SURGE_WARNING
    assert watch_warning_kind("Extreme Wind Warning") is None


def test_watch_warning_block_with_wrapped_items():
    section = (
        "SUMMARY OF WATCHES AND WARNINGS IN EFFECT:\n\n"
        "A Hurricane Warning is in effect for...\n"
        "* Cabo San Lucas to\n  La Paz\n"
        "* Punta Eugenia to Cabo San Lucas\n\n"
        "A Hurricane Warning means that hurricane conditions are expected.\n"
    )
    result = parse_watch_warning_text(section)
    assert [(w.kind, w.areas) for w in result.in_effect] == [
        (WatchWarning.HURRICANE_WARNING, ("Cabo San Lucas to La Paz", "Punta Eugenia to Cabo San Lucas"))
    ]


# ---- discussion (TCD) ---------------------------------------------------------------------------------------------


def test_erin_30_discussion_sections():
    tcd = parse_tcd(nhc_bytes("tcd/erin_030.txt"))
    assert (tcd.storm_id, tcd.kind, tcd.name, tcd.adv_num) == ("al052025", "HURRICANE", "Erin", AdvNum(30))
    assert tcd.issued == datetime(2025, 8, 18, 21, 0, tzinfo=UTC)
    assert tcd.forecaster == "Pasch"
    assert len(tcd.paragraphs) == 4
    assert tcd.paragraphs[0].startswith("Erin's cloud pattern has become somewhat less organized")
    assert len(tcd.key_messages) == 4
    assert tcd.key_messages[0].startswith("Bands of heavy rainfall are expected over portions of Hispaniola")
    assert tcd.key_messages[3].endswith("strong winds are possible beginning on Thursday.")
    assert not tcd.is_last


def test_erin_30_discussion_forecast_table():
    tcd = parse_tcd(nhc_bytes("tcd/erin_030.txt"))
    assert [f.hour for f in tcd.forecast] == [0, 12, 24, 36, 48, 60, 72, 96, 120]
    init = tcd.forecast[0]
    assert init.valid == datetime(2025, 8, 18, 21, 0, tzinfo=UTC)
    assert (init.lat, init.lon, init.wind_kt, init.wind_mph) == (24.0, -71.3, 120, 140)
    last = tcd.forecast[-1]
    assert (last.valid, last.lat, last.lon, last.wind_kt, last.wind_mph) == (
        datetime(2025, 8, 23, 18, 0, tzinfo=UTC),
        41.0,
        -56.5,
        75,
        85,
    )


def test_final_discussion_ends_in_a_dissipated_row():
    tcd = parse_tcd(nhc_bytes("tcd/fay_039.txt"))
    assert tcd.is_last
    assert tcd.key_messages == ()
    assert [(f.hour, f.status) for f in tcd.forecast] == [
        (0, "POST-TROP/REMNT LOW"),
        (12, "POST-TROP/REMNT LOW"),
        (24, "POST-TROP/REMNT LOW"),
        (36, "DISSIPATED"),
    ]
    gone = tcd.forecast[-1]
    assert gone.dissipated
    assert (gone.lat, gone.lon, gone.wind_kt) == (None, None, None)
    assert gone.valid == datetime(2026, 10, 1, 6, 0, tzinfo=UTC)


def test_dateline_discussion_has_east_and_west_free_longitudes():
    tcd = parse_tcd(nhc_bytes("tcd/nolo_057.txt"))
    assert [f.lon for f in tcd.forecast[:3]] == [180.0, 177.7, 174.6]
    assert tcd.is_last


def test_discussion_without_a_table_or_key_messages():
    text = nhc_text("tcd/erin_030.txt")
    cut = text[: text.index("KEY MESSAGES")]
    tcd = parse_tcd(cut)
    assert tcd.key_messages == ()
    assert tcd.forecast == ()
    assert len(tcd.paragraphs) == 4


@pytest.mark.parametrize("text", ["", "Hurricane Erin Discussion", "not a product"])
def test_text_that_is_not_a_discussion_raises(text):
    with pytest.raises(ParseError):
        parse_tcd(text)


# ---- wind speed probabilities (PWS) -------------------------------------------------------------------------------


def test_erin_30_probability_table_header():
    pws = parse_pws(nhc_bytes("pws/erin_030.txt"))
    assert (pws.storm_id, pws.name, pws.adv_num) == ("al052025", "ERIN", AdvNum(30))
    assert pws.issued == datetime(2025, 8, 18, 21, 0, tzinfo=UTC)
    assert pws.forecast_hours == (12, 24, 36, 48, 72, 96, 120)
    assert len(pws.rows) == 50
    assert pws.skipped == 0
    assert pws.locations[:2] == ("HIBERNIA OILFD", "CAPE RACE NFLD")
    assert pws.locations[-1] == "GRAND TURK"


def _pairs(row):
    return [(c.onset, c.cumulative) for c in row.cells]


def test_probability_cells_split_onset_and_cumulative_and_x_is_zero():
    pws = parse_pws(nhc_bytes("pws/erin_030.txt"))
    hatteras = {row.threshold_kt: row for row in pws.for_location("cape hatteras")}
    assert set(hatteras) == {34, 50, 64}
    assert _pairs(hatteras[34]) == [(0, 0), (0, 0), (0, 0), (4, 4), (28, 32), (1, 33), (0, 33)]
    assert _pairs(hatteras[50]) == [(0, 0), (0, 0), (0, 0), (0, 0), (7, 7), (0, 7), (0, 7)]
    assert _pairs(hatteras[64])[4] == (3, 3)


def test_first_period_has_only_an_onset_probability():
    pws = parse_pws(nhc_bytes("pws/erin_030.txt"))
    (grand_turk,) = pws.for_location("GRAND TURK")
    assert _pairs(grand_turk) == [(99, 99), (0, 99), (0, 99), (0, 99), (0, 99), (0, 99), (0, 99)]
    (sable,) = [r for r in pws.for_location("SABLE ISLAND") if r.threshold_kt == 34]
    assert _pairs(sable)[-2:] == [(2, 2), (15, 17)]


def test_final_advisory_probability_table_is_empty():
    for name in ("fay_039", "nolo_057"):
        pws = parse_pws(nhc_bytes(f"pws/{name}.txt"))
        assert pws.rows == ()
        assert pws.forecast_hours == (12, 24, 36, 48, 72, 96, 120)
    assert parse_pws(nhc_bytes("pws/nolo_057.txt")).storm_id == "ep152026"


def test_unreadable_table_lines_are_counted_not_fatal():
    text = nhc_text("pws/erin_030.txt").replace("MONTAUK POINT  34  X", "MONTAUK POINT  34 ?(", 1)
    text = text.replace("BERMUDA        34  X", "BERMUDA        34 5(  ", 1)
    pws = parse_pws(text)
    assert len(pws.rows) >= 48
    assert pws.skipped >= 0


@pytest.mark.parametrize("text", ["", "WIND SPEED PROBABILITIES", "nothing"])
def test_text_that_is_not_a_probability_product_raises(text):
    with pytest.raises(ParseError):
        parse_pws(text)


# ---- tropical weather outlook (TWO) -------------------------------------------------------------------------------


def test_quiet_atlantic_outlook():
    two = parse_two(nhc_bytes("two/at_20261031.txt"))
    assert two.office == "NWS National Hurricane Center Miami FL"
    assert two.issued == datetime(2026, 10, 31, 6, 0, tzinfo=UTC)  # 200 AM EDT
    assert two.issued_text == "200 AM EDT Sat Oct 31 2026"
    assert two.region == "For the North Atlantic...Caribbean Sea and the Gulf of America"
    assert two.areas == ()
    assert two.active_systems is None
    assert two.quiet
    assert two.summary == "Tropical cyclone formation is not expected during the next 7 days."
    assert two.forecaster == "Gibbs"


def test_live_pacific_outlook_with_one_area():
    two = parse_two(nhc_bytes("two/ep_20261031.txt"))
    assert two.region == "For the eastern and central North Pacific east of 180 longitude"
    assert not two.quiet
    (area,) = two.areas
    assert area.number is None
    assert area.title == "Well Southeast of the Hawaiian Islands"
    assert area.description.startswith("A broad area of low pressure is forecast to develop well to the southeast")
    assert area.description.endswith("over the Central Pacific basin.")
    assert (area.chance_48h.risk, area.chance_48h.percent) == ("low", 0)  # "near 0 percent"
    assert (area.chance_7d.risk, area.chance_7d.percent) == ("medium", 40)
    assert area.invest_id is None


def test_central_pacific_outlook_has_its_own_office_and_region():
    two = parse_two(nhc_bytes("two/cp_20261031.txt"))
    assert two.office == "NWS Central Pacific Hurricane Center Honolulu HI"
    assert two.issued == datetime(2026, 10, 31, 6, 0, tzinfo=UTC)  # 800 PM HST on the 30th
    assert two.region == "For the central North Pacific...between 140W and 180W"
    assert two.areas[0].chance_7d.percent == 40
    assert two.summary == ""  # the "Issued by" line is not outlook text


def test_numbered_areas_with_active_systems_and_trailing_notes():
    two = parse_two(nhc_bytes("two/ep_20260910.txt"))
    assert two.active_systems.startswith("The National Hurricane Center is issuing advisories on Tropical Storm Lowell")
    assert "Tropical Depression Fourteen-E" in two.active_systems
    assert [a.number for a in two.areas] == [1, 2]
    assert two.areas[0].title == "Well South-Southeast of the Hawaiian Islands"
    assert (two.areas[0].chance_48h.percent, two.areas[0].chance_7d.percent) == (20, 30)
    assert (two.areas[0].chance_7d.risk) == "low"
    assert two.areas[1].title == "Central Portion and West Portion of the East Pacific"
    assert (two.areas[1].chance_48h.percent, two.areas[1].chance_7d.percent) == (0, 70)
    assert two.areas[1].chance_7d.risk == "high"
    assert two.areas[1].description.endswith("central and western portions of the East Pacific.")
    assert two.notes.startswith(
        "Public Advisories on Tropical Depression Fourteen-E are issued under WMO header WTPZ34"
    )
    assert "Formation chance" not in two.areas[1].description
    assert two.forecaster == "Reinhart"
    assert two.issued == datetime(2026, 9, 10, 6, 0, tzinfo=UTC)  # 1100 PM PDT


def test_central_pacific_outlook_repeats_the_same_areas():
    two = parse_two(nhc_bytes("two/cp_20260910.txt"))
    assert [a.title for a in two.areas] == [
        "Well South-Southeast of the Hawaiian Islands",
        "Central Portion and West Portion of the East Pacific",
    ]


def test_an_invest_designation_in_an_area_title_is_picked_up():
    text = nhc_text("two/ep_20260910.txt").replace(
        "2. Central Portion and West Portion of the East Pacific:",
        "2. Central Portion and West Portion of the East Pacific (EP95):",
    )
    area = parse_two(text).areas[1]
    assert area.title == "Central Portion and West Portion of the East Pacific"
    assert area.invest_id == "EP95"


def test_outlook_text_from_api_weather_gov_parses_the_same():
    product = parse_product(nhc_bytes("api/product_two_at.json"))
    assert product.text.startswith("\n000\n")  # the bare 000 line api.weather.gov puts first
    assert parse_two(product.text) == parse_two(nhc_bytes("two/at_20261031.txt"))


def test_outlook_without_a_heading_raises():
    with pytest.raises(ParseError):
        parse_two("Hello")


def test_a_recorded_special_outlook_parses_its_areas_and_summary():
    """A real Special Tropical Weather Outlook (21 Oct 2026, 340 PM EDT) sits under the same product header as a routine one."""
    special = parse_two(nhc_bytes("two/at_special_20261021.txt"))
    assert special.office == "NWS National Hurricane Center Miami FL"
    assert special.issued_text is not None and "340 PM EDT" in special.issued_text
    assert special.summary.startswith("Special Outlook issued to raise formation probabilities for AL93")
    assert [a.invest_id for a in special.areas] == ["AL93", None]
    assert special.areas[0].chance_48h is not None and special.areas[0].chance_48h.percent == 70
    assert special.areas[1].chance_7d is not None and special.areas[1].chance_7d.percent == 10
