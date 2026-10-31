from datetime import UTC, datetime

import pytest

from eyewall.models.storm import AdvNum
from eyewall.models.wind import QuadrantRadii
from eyewall.providers.base import ParseError
from eyewall.providers.nhc.tcm import parse_tcm, split_kind_and_name
from tests.nhc_fixtures import nhc_bytes, nhc_text


def _fix(advisory, tau):
    return next(f for f in advisory.fixes if f.tau == tau)


# ---- Hurricane Erin, advisory 30: everything present -------------------------------------------------------------


def test_erin_30_header_and_center():
    tcm = parse_tcm(nhc_bytes("tcm/erin_030.txt"))
    assert tcm.storm_id == "al052025"
    assert (tcm.kind, tcm.name) == ("HURRICANE", "ERIN")
    assert tcm.adv_num == AdvNum(30)
    assert tcm.issued == datetime(2025, 8, 18, 21, 0, tzinfo=UTC)
    assert tcm.synoptic == datetime(2025, 8, 18, 18, 0, tzinfo=UTC)
    assert (tcm.lat, tcm.lon) == (24.0, -71.3)
    assert tcm.center_kind == "HURRICANE"
    assert tcm.position_accuracy_nm == 20
    assert (tcm.movement_text, tcm.movement_dir_deg, tcm.movement_speed_kt) == ("NORTHWEST", 310, 9)
    assert tcm.pressure_mb == 937
    assert (tcm.max_wind_kt, tcm.gust_kt) == (120, 145)
    assert tcm.eye_diameter_nm is None
    assert not tcm.is_final
    assert not tcm.post_tropical
    assert tcm.next_advisory == datetime(2025, 8, 19, 3, 0, tzinfo=UTC)


def test_erin_30_wind_radii_by_quadrant():
    tcm = parse_tcm(nhc_text("tcm/erin_030.txt"))
    assert tcm.radii.kt64 == QuadrantRadii(ne=70, se=60, sw=40, nw=40)
    assert tcm.radii.kt50 == QuadrantRadii(ne=110, se=110, sw=70, nw=70)
    assert tcm.radii.kt34 == QuadrantRadii(ne=200, se=200, sw=140, nw=170)
    assert tcm.radii.for_threshold(34) is tcm.radii.kt34
    assert tcm.radii.for_threshold(12) is None
    assert tcm.radii.kt34.largest == 200
    assert not tcm.radii.empty
    assert (tcm.seas.height, tcm.seas.unit) == (4, "M")
    assert tcm.seas.radii == QuadrantRadii(ne=420, se=360, sw=180, nw=300)


def test_erin_30_prior_position():
    prior = parse_tcm(nhc_bytes("tcm/erin_030.txt")).prior
    assert prior.time == datetime(2025, 8, 18, 18, 0, tzinfo=UTC)
    assert (prior.lat, prior.lon) == (23.6, -71.0)


def test_erin_30_forecast_fixes_count_hours_from_the_synoptic_time():
    tcm = parse_tcm(nhc_bytes("tcm/erin_030.txt"))
    assert [f.tau for f in tcm.fixes] == [12, 24, 36, 48, 60, 72, 96, 120]
    assert [f.tau for f in tcm.forecast_fixes] == [12, 24, 36, 48, 60, 72]
    assert [f.tau for f in tcm.outlook_fixes] == [96, 120]
    first = _fix(tcm, 12)
    assert first.valid == datetime(2025, 8, 19, 6, 0, tzinfo=UTC)
    assert (first.lat, first.lon) == (24.9, -71.9)
    assert (first.max_wind_kt, first.gust_kt) == (120, 145)
    assert first.status is None
    assert not first.dissipated
    last = _fix(tcm, 120)
    assert last.valid == datetime(2025, 8, 23, 18, 0, tzinfo=UTC)
    assert (last.lat, last.lon, last.max_wind_kt, last.gust_kt) == (41.0, -56.5, 75, 90)


def test_erin_30_outlook_fixes_carry_only_34_and_50_kt_radii():
    tcm = parse_tcm(nhc_bytes("tcm/erin_030.txt"))
    day4 = _fix(tcm, 96)
    assert day4.outlook
    assert day4.radii.kt64 is None
    assert day4.radii.kt50 == QuadrantRadii(ne=150, se=150, sw=130, nw=120)
    assert day4.radii.kt34 == QuadrantRadii(ne=270, se=290, sw=240, nw=240)
    assert _fix(tcm, 24).radii.kt64 == QuadrantRadii(ne=70, se=60, sw=40, nw=40)
    assert _fix(tcm, 24).radii.kt50 == QuadrantRadii(ne=110, se=110, sw=70, nw=80)


# ---- Erin 46: a late post-tropical advisory with fewer radii and zeros ---------------------------------------------


def test_erin_46_is_post_tropical_with_fewer_radii_later_on():
    tcm = parse_tcm(nhc_bytes("tcm/erin_046.txt"))
    assert tcm.adv_num == AdvNum(46)
    assert tcm.post_tropical
    assert tcm.kind == "POST-TROPICAL CYCLONE"
    assert tcm.is_final
    assert tcm.next_advisory is None
    assert (tcm.max_wind_kt, tcm.gust_kt, tcm.pressure_mb) == (80, 100, 957)
    assert tcm.movement_text == "EAST-NORTHEAST"
    assert _fix(tcm, 12).status == "POST-TROP/EXTRATROP"
    # 64 kt radii: present at 12 to 60 h (with zero quadrants kept as 0), omitted at 72 h and beyond.
    assert _fix(tcm, 60).radii.kt64 == QuadrantRadii(ne=0, se=60, sw=60, nw=0)
    assert _fix(tcm, 72).radii.kt64 is None
    assert _fix(tcm, 72).radii.kt50 == QuadrantRadii(ne=0, se=90, sw=90, nw=0)
    assert _fix(tcm, 96).radii.kt50 is None
    assert _fix(tcm, 120).radii.kt34 == QuadrantRadii(ne=0, se=200, sw=330, nw=120)


# ---- odd cases from the 2024 to 2026 seasons ----------------------------------------------------------------------


def test_post_tropical_dissipated_advisory_has_no_radii_and_a_position_free_last_fix():
    tcm = parse_tcm(nhc_bytes("tcm/fay_039.txt"))
    assert (tcm.storm_id, tcm.kind, tcm.name, tcm.adv_num) == ("al062026", "POST-TROPICAL CYCLONE", "FAY", AdvNum(39))
    assert tcm.radii.empty
    assert tcm.seas is None
    assert (tcm.max_wind_kt, tcm.gust_kt, tcm.pressure_mb) == (25, 35, 1011)
    assert [f.tau for f in tcm.fixes] == [12, 24, 36]
    assert _fix(tcm, 12).status == "POST-TROP/REMNT LOW"
    assert _fix(tcm, 12).radii.empty
    gone = _fix(tcm, 36)
    assert gone.dissipated
    assert gone.valid == datetime(2026, 10, 1, 6, 0, tzinfo=UTC)
    assert (gone.lat, gone.lon, gone.max_wind_kt) == (None, None, None)
    assert tcm.is_final


def test_remnants_of_prefix_and_a_single_dissipated_fix():
    tcm = parse_tcm(nhc_bytes("tcm/vance_035.txt"))
    assert (tcm.kind, tcm.name, tcm.adv_num) == ("REMNANTS OF", "VANCE", AdvNum(35))
    assert tcm.remnants
    assert tcm.center_kind == "REMNANTS OF"
    assert tcm.storm_id == "ep222026"
    assert [(f.tau, f.dissipated) for f in tcm.fixes] == [(12, True)]


def test_east_longitude_and_a_west_to_east_dateline_crossing():
    tcm = parse_tcm(nhc_bytes("tcm/nolo_057.txt"))
    assert tcm.storm_id == "ep152026"  # an ep id in a CP-bin advisory
    assert (tcm.kind, tcm.name) == ("HURRICANE", "NOLO")
    assert (tcm.lat, tcm.lon) == (24.2, 180.0)  # "180.0E"
    assert tcm.prior.lon == -179.2  # the earlier position was still in the west
    assert [f.lon for f in tcm.fixes[:3]] == [177.7, 174.6, 170.9]  # "177.7E"
    assert tcm.eye_diameter_nm == 30
    assert tcm.radii.kt64 == QuadrantRadii(ne=30, se=25, sw=20, nw=30)
    assert tcm.is_final
    assert tcm.issued == datetime(2026, 10, 4, 21, 0, tzinfo=UTC)


def test_cp_post_tropical_remnant_low_without_radii():
    tcm = parse_tcm(nhc_bytes("tcm/olana_007.txt"))
    assert tcm.storm_id == "cp032026"
    assert tcm.name == "OLANA"
    assert tcm.radii.empty
    assert (_fix(tcm, 12).lat, _fix(tcm, 12).lon) == (13.3, -175.1)
    assert _fix(tcm, 24).dissipated
    assert tcm.prior.time == datetime(2026, 10, 27, 0, 0, tzinfo=UTC)


def test_partial_radii_with_zero_quadrants_and_a_missing_64_kt_line():
    tcm = parse_tcm(nhc_bytes("tcm/josephine_005.txt"))
    assert tcm.storm_id == "al102026"
    assert tcm.radii.kt64 is None
    assert tcm.radii.kt50 == QuadrantRadii(ne=0, se=0, sw=100, nw=110)
    assert tcm.radii.kt34 == QuadrantRadii(ne=360, se=110, sw=170, nw=240)
    assert _fix(tcm, 12).radii.kt64 == QuadrantRadii(ne=0, se=0, sw=60, nw=60)
    assert _fix(tcm, 24).radii.kt64 is None
    assert _fix(tcm, 60).radii.kt50 is None
    assert _fix(tcm, 60).radii.kt34 == QuadrantRadii(ne=150, se=180, sw=180, nw=200)
    assert _fix(tcm, 72).dissipated


def test_potential_tropical_cyclone_has_one_radii_line_and_feet_of_seas():
    tcm = parse_tcm(nhc_bytes("tcm/ptc08_001.txt"))
    assert tcm.potential
    assert (tcm.kind, tcm.name, tcm.adv_num, tcm.storm_id) == (
        "POTENTIAL TROPICAL CYCLONE",
        "EIGHT",
        AdvNum(1),
        "al082024",
    )
    assert tcm.center_kind == "POTENTIAL TROP CYCLONE"
    assert tcm.radii.kt34 == QuadrantRadii(ne=150, se=0, sw=0, nw=90)
    assert tcm.radii.kt50 is None
    assert (tcm.seas.height, tcm.seas.unit) == (12, "FT")
    assert [f.status for f in tcm.fixes[:4]] == ["TROPICAL CYCLONE", "INLAND", "POST-TROPICAL", "POST-TROPICAL"]
    assert _fix(tcm, 96).dissipated
    assert _fix(tcm, 96).outlook
    assert tcm.issued == datetime(2024, 9, 15, 21, 0, tzinfo=UTC)


# ---- input forms and bad input ------------------------------------------------------------------------------------


def test_crlf_and_bytes_and_str_inputs_parse_the_same():
    text = nhc_text("tcm/erin_030.txt")
    assert parse_tcm(text.replace("\n", "\r\n")) == parse_tcm(text) == parse_tcm(text.encode())


def test_the_api_weather_gov_wrapper_lines_are_ignored():
    wrapped = "\n000\nWTNT25 KNHC 182100\nTCMAT5\n\n" + nhc_text("tcm/erin_030.txt").split("ZCZC MIATCMAT5 ALL\n", 1)[1]
    assert parse_tcm(wrapped).adv_num == AdvNum(30)


def test_a_tcm_missing_optional_lines_still_parses():
    lines = [
        line
        for line in nhc_text("tcm/erin_030.txt").splitlines()
        if not line.startswith(("POSITION ACCURATE", "PRESENT MOVEMENT", "ESTIMATED MINIMUM"))
    ]
    tcm = parse_tcm("\n".join(lines))
    assert tcm.position_accuracy_nm is None
    assert tcm.movement_dir_deg is None
    assert tcm.movement_speed_kt is None
    assert tcm.pressure_mb is None
    assert tcm.max_wind_kt == 120
    assert len(tcm.fixes) == 8


def test_an_unrecognised_status_after_a_position_is_kept_as_text():
    text = nhc_text("tcm/erin_030.txt").replace("24.9N  71.9W", "24.9N  71.9W...OVER LAND")
    assert _fix(parse_tcm(text), 12).status == "OVER LAND"


def test_a_truncated_product_keeps_the_fixes_it_has():
    text = nhc_text("tcm/erin_030.txt")
    cut = text[: text.index("FORECAST VALID 20/0600Z")]
    tcm = parse_tcm(cut)
    assert [f.tau for f in tcm.fixes] == [12, 24]


@pytest.mark.parametrize(
    "text",
    ["", "HELLO", "HURRICANE ERIN FORECAST/ADVISORY NUMBER  30\nno center line", "<html>503</html>"],
)
def test_text_that_is_not_a_tcm_raises(text):
    with pytest.raises(ParseError):
        parse_tcm(text)


def test_a_tcm_with_no_issue_time_raises():
    text = nhc_text("tcm/erin_030.txt").replace("2100 UTC MON AUG 18 2025", "SOMETIME")
    with pytest.raises(ParseError):
        parse_tcm(text)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("HURRICANE ERIN", ("HURRICANE", "ERIN")),
        ("TROPICAL DEPRESSION NINETEEN-E", ("TROPICAL DEPRESSION", "NINETEEN-E")),
        ("Post-Tropical Cyclone Isaias", ("POST-TROPICAL CYCLONE", "Isaias")),
        ("SUBTROPICAL STORM ANA", ("SUBTROPICAL STORM", "ANA")),
        ("POTENTIAL TROPICAL CYCLONE TWO", ("POTENTIAL TROPICAL CYCLONE", "TWO")),
        ("HURRICANE", ("HURRICANE", None)),
        ("SOMETHING ELSE ENTIRELY", ("SOMETHING ELSE ENTIRELY", None)),
    ],
)
def test_kind_and_name_split(title, expected):
    assert split_kind_and_name(title) == expected
