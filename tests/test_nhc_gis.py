import io
import zipfile
from collections import Counter
from datetime import UTC, datetime

import pytest

from eyewall.models.storm import AdvNum
from eyewall.models.wind import QuadrantRadii
from eyewall.palette import WatchWarning
from eyewall.providers.base import ParseError
from eyewall.providers.nhc.gis import (
    parse_best_track_zip,
    parse_forecast_zip,
    parse_radii_zip,
    read_layer_names,
    wrap_lon,
)
from eyewall.providers.nhc.two import parse_gtwo_zip
from tests.nhc_fixtures import gis_bytes


def _without(data: bytes, *needles: str) -> bytes:
    """A copy of a zip with every member whose name contains one of the needles removed."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(out, "w") as target:
        for info in source.infolist():
            if not any(needle in info.filename for needle in needles):
                target.writestr(info, source.read(info))
    return out.getvalue()


def _replaced(data: bytes, needle: str, content: bytes) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(out, "w") as target:
        for info in source.infolist():
            target.writestr(info, content if needle in info.filename else source.read(info))
    return out.getvalue()


# ---- forecast zip: Erin advisory 30 -------------------------------------------------------------------------------


def test_erin_forecast_zip_metadata():
    gis = parse_forecast_zip(gis_bytes("erin_5day_030.zip"))
    assert (gis.storm_name, gis.storm_type) == ("Erin", "HU")
    assert gis.adv_num == AdvNum(30)
    assert gis.adv_date_text == "500 PM EDT Mon Aug 18 2025"
    assert gis.issued == datetime(2025, 8, 18, 21, 0, tzinfo=UTC)


def test_erin_cone_is_a_single_ring_that_closes():
    gis = parse_forecast_zip(gis_bytes("erin_5day_030.zip"))
    assert len(gis.cone) == 1  # the cone polygon has one ring
    ring = gis.cone[0]
    assert len(ring) == 2088
    assert ring[0] == ring[-1]
    assert ring[0] == (23.75879, -71.39744)  # (lat, lon)
    assert all(-90 <= lat <= 90 and -180 < lon <= 180 for lat, lon in ring)


def test_erin_watch_warning_lines_carry_the_tcww_codes():
    gis = parse_forecast_zip(gis_bytes("erin_5day_030.zip"))
    assert len(gis.watch_warnings) == 12
    assert Counter(s.code for s in gis.watch_warnings) == {"TWA": 7, "TWR": 5}
    kinds = Counter(s.kind for s in gis.watch_warnings)
    assert kinds == {WatchWarning.TROPICAL_STORM_WATCH: 7, WatchWarning.TROPICAL_STORM_WARNING: 5}
    first = gis.watch_warnings[0]
    assert first.code == "TWA"
    assert len(first.points) == 7
    assert first.points[0] == (34.69, -76.67)


def test_erin_forecast_points():
    gis = parse_forecast_zip(gis_bytes("erin_5day_030.zip"))
    assert [p.tau for p in gis.points] == [0, 12, 24, 36, 48, 60, 72, 96, 120]
    now = gis.points[0]
    assert (now.lat, now.lon) == (24.0, -71.3)  # the exact center from the shape, not the rounded LAT/LON fields
    assert (now.max_wind_kt, now.gust_kt, now.mslp_mb) == (120, 145, 937)
    assert (now.storm_type, now.development, now.saffir_simpson) == ("MH", "Major Hurricane", 4)
    assert (now.direction_deg, now.speed_kt) == (310, 9)
    assert now.valid == datetime(2025, 8, 18, 18, 0, tzinfo=UTC)
    assert (now.date_label, now.local_label, now.timezone) == ("5:00 PM Mon", "2025-08-18 2:00 PM Mon EDT", "EDT")
    later = gis.points[1]
    assert later.valid == datetime(2025, 8, 19, 6, 0, tzinfo=UTC)
    assert (later.lat, later.lon) == (24.9, -71.9)


def test_nines_fill_values_become_none():
    gis = parse_forecast_zip(gis_bytes("erin_5day_030.zip"))
    later = gis.points[1]
    assert later.mslp_mb is None  # 9999 in the file
    assert later.direction_deg is None
    assert later.speed_kt is None
    assert later.max_wind_kt == 120


def test_erin_track_line():
    gis = parse_forecast_zip(gis_bytes("erin_5day_030.zip"))
    assert len(gis.track) == 1
    assert len(gis.track[0]) == 9
    assert gis.track[0][0] == (24.0, -71.3)
    assert gis.track[0][-1] == (41.0, -56.5)


def test_intermediate_advisory_zip_has_the_a_suffix():
    gis = parse_forecast_zip(gis_bytes("erin_5day_030A.zip"))
    assert gis.adv_num == AdvNum(30, "A")
    assert gis.adv_num.intermediate
    assert gis.adv_date_text == "800 PM EDT Mon Aug 18 2025"
    assert gis.issued == datetime(2025, 8, 19, 0, 0, tzinfo=UTC)
    assert len(gis.cone) == 1
    assert len(gis.cone[0]) == 2082  # the cone differs from the full advisory's
    assert (gis.points[0].lat, gis.points[0].lon) == (24.1, -71.5)
    assert gis.points[0].max_wind_kt == 115
    assert len(gis.watch_warnings) == 12


def test_post_tropical_zip_has_no_warnings_and_fewer_points():
    gis = parse_forecast_zip(gis_bytes("fay_5day_latest.zip"))
    assert gis.adv_num == AdvNum(39)
    assert [p.tau for p in gis.points] == [0, 12, 24]
    assert gis.watch_warnings == ()
    assert len(gis.cone) == 1


def test_dateline_geometry_is_wrapped_to_one_convention():
    gis = parse_forecast_zip(gis_bytes("nolo_5day_057.zip"))
    assert gis.storm_name == "Nolo"
    assert gis.watch_warnings == ()
    assert gis.points[0].lon == 180.0  # published as -180.0
    assert gis.points[1].lon == 177.7  # published as -182.3 in the point layer
    track = gis.track[0]
    assert track[0] == (24.2, 180.0)
    assert track[-1] == (29.4, 149.7)  # published as -210.3
    assert all(-180 < lon <= 180 for _, lon in track)
    cone_lons = [lon for ring in gis.cone for _, lon in ring]
    assert all(-180 < lon <= 180 for lon in cone_lons)
    assert min(cone_lons) < -179.9 and max(cone_lons) > 179.9  # the cone straddles the dateline
    assert min(cone_lons) < -179 and any(lon < 150 for lon in cone_lons)


def test_wrap_lon_keeps_in_range_values_exactly():
    assert wrap_lon(-23.1) == -23.1
    assert wrap_lon(180.0) == 180.0
    assert wrap_lon(-180.0) == 180.0
    assert wrap_lon(-182.3) == pytest.approx(177.7)
    assert wrap_lon(181.0) == pytest.approx(-179.0)
    assert wrap_lon(-210.3) == pytest.approx(149.7)


def test_missing_layers_come_back_empty():
    data = gis_bytes("erin_5day_030.zip")
    no_cone = parse_forecast_zip(_without(data, "_5day_pgn"))
    assert no_cone.cone == ()
    assert len(no_cone.points) == 9
    only_points = parse_forecast_zip(_without(data, "_5day_pgn", "_5day_lin", "_ww_wwlin"))
    assert (only_points.cone, only_points.track, only_points.watch_warnings) == ((), (), ())
    assert only_points.storm_name == "Hurricane Erin"  # the points layer spells the name out
    nothing = parse_forecast_zip(_without(data, ".shp", ".dbf", ".shx"))
    assert nothing.points == () and nothing.storm_name is None and nothing.adv_num is None


def test_an_unreadable_layer_is_dropped_not_fatal():
    broken = _replaced(gis_bytes("erin_5day_030.zip"), "_5day_pgn.shp", b"garbage")
    gis = parse_forecast_zip(broken)
    assert gis.cone == ()
    assert len(gis.points) == 9


def test_unknown_tcww_code_is_kept_with_no_kind():
    data = gis_bytes("erin_5day_030.zip")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        dbf = archive.read("al052025-030_ww_wwlin.dbf")
    patched = _replaced(data, "_ww_wwlin.dbf", dbf.replace(b"TWR", b"XYZ"))
    gis = parse_forecast_zip(patched)
    assert Counter(s.code for s in gis.watch_warnings) == {"TWA": 7, "XYZ": 5}
    assert {s.kind for s in gis.watch_warnings if s.code == "XYZ"} == {None}
    assert {s.kind for s in gis.watch_warnings if s.code == "TWA"} == {WatchWarning.TROPICAL_STORM_WATCH}


@pytest.mark.parametrize("parser", [parse_forecast_zip, parse_radii_zip, parse_best_track_zip, parse_gtwo_zip])
def test_bytes_that_are_not_a_zip_raise(parser):
    with pytest.raises(ParseError):
        parser(b"<html>not found</html>")


def test_layer_names_are_listed():
    names = read_layer_names(gis_bytes("erin_5day_030.zip"))
    assert names == (
        "al052025-030_5day_lin",
        "al052025-030_5day_pgn",
        "al052025-030_5day_pts",
        "al052025-030_ww_wwlin",
    )


# ---- wind radii zip -----------------------------------------------------------------------------------------------


def test_erin_initial_and_forecast_radii_polygons():
    radii = parse_radii_zip(gis_bytes("erin_fcst_030.zip"))
    assert (radii.storm_id, radii.adv_num) == ("al052025", AdvNum(30))
    assert [(p.kt, p.tau) for p in radii.initial] == [(34, 0), (50, 0), (64, 0)]
    assert radii.initial[0].radii == QuadrantRadii(ne=200, se=200, sw=140, nw=170)
    assert radii.initial[2].radii == QuadrantRadii(ne=70, se=60, sw=40, nw=40)
    assert len(radii.initial[0].rings) == 1
    assert len(radii.initial[0].rings[0]) == 361
    assert radii.initial[0].valid == datetime(2025, 8, 18, 21, 0, tzinfo=UTC)
    assert radii.initial[0].synoptic == datetime(2025, 8, 18, 18, 0, tzinfo=UTC)
    assert len(radii.forecast) == 25
    assert radii.forecast[3].tau == 12
    assert radii.forecast[3].valid == datetime(2025, 8, 19, 6, 0, tzinfo=UTC)
    assert radii.forecast[3].radii == QuadrantRadii(ne=200, se=200, sw=140, nw=180)
    assert max(p.tau for p in radii.forecast) == 120
    assert {p.kt for p in radii.forecast} == {34, 50, 64}


def test_dateline_radii_are_wrapped():
    radii = parse_radii_zip(gis_bytes("nolo_fcst_057.zip"))
    assert radii.storm_id == "ep152026"
    assert len(radii.initial) == 3
    assert len(radii.forecast) == 24
    lons = [lon for polygon in radii.initial + radii.forecast for ring in polygon.rings for _, lon in ring]
    assert all(-180 < lon <= 180 for lon in lons)
    assert min(lons) < -170 and max(lons) > 170  # published as -182.4 and 180.1 on either side of the line


def test_radii_zip_missing_a_layer():
    data = gis_bytes("erin_fcst_030.zip")
    only_initial = parse_radii_zip(_without(data, "forecastradii"))
    assert only_initial.forecast == ()
    assert len(only_initial.initial) == 3
    assert parse_radii_zip(_without(data, ".shp", ".dbf")).initial == ()


# ---- best track zip -----------------------------------------------------------------------------------------------


def test_erin_best_track_points_and_segments():
    best = parse_best_track_zip(gis_bytes("erin_best_track.zip"))
    assert best.storm_id == "al052025"
    assert len(best.points) == 68
    first = best.points[0]
    assert first.time == datetime(2025, 8, 11, 0, 0, tzinfo=UTC)
    assert (first.lat, first.lon) == (16.5, -23.1)
    assert (first.storm_name, first.storm_type, first.intensity_kt, first.mslp_mb) == ("INVEST", "TD", 30, 1007)
    last = best.points[-1]
    assert (last.storm_name, last.storm_type, last.intensity_kt, last.mslp_mb) == ("ERIN", "EX", 40, 985)
    assert max(p.intensity_kt for p in best.points) == 140
    assert len(best.segments) == 13
    assert Counter(s.storm_type for s in best.segments) == {"HU": 11, "TD": 1, "TS": 1}
    assert best.segments[0].points == ((16.5, -23.1), (17.2, -25.2))


# ---- graphical outlook zips ---------------------------------------------------------------------------------------


def test_live_outlook_zip_with_one_pacific_area():
    gtwo = parse_gtwo_zip(gis_bytes("gtwo_20261031.zip"))
    assert gtwo.issued == datetime(2026, 10, 31, 5, 7, tzinfo=UTC)
    (area,) = gtwo.systems
    assert (area.basin_label, area.area_id) == ("Pacific", "1")
    assert (area.prob_2day, area.risk_2day) == (0, "low")
    assert (area.prob_7day, area.risk_7day) == (40, "medium")
    assert len(area.polygons) == 1
    assert len(area.polygons[0]) == 300
    assert area.lines == ()
    assert area.point is None
    assert not gtwo.empty
    lat, lon = area.polygons[0][0]
    assert (round(lat, 3), round(lon, 3)) == (4.329, -142.007)


def test_outlook_zip_with_three_areas_joins_polygon_line_and_point():
    gtwo = parse_gtwo_zip(gis_bytes("gtwo_20250919.zip"))
    assert gtwo.issued == datetime(2025, 9, 19, 11, 33, tzinfo=UTC)
    summary = [(s.basin_label, s.area_id, s.prob_2day, s.risk_2day, s.prob_7day, s.risk_7day) for s in gtwo.systems]
    assert summary == [
        ("Atlantic", "1", 0, "low", 20, "low"),
        ("Pacific", "1", 60, "medium", 60, "medium"),
        ("Pacific", "2", 20, "low", 60, "medium"),
    ]
    atlantic = gtwo.systems[0]
    assert len(atlantic.polygons) == 1 and len(atlantic.lines) == 1
    assert atlantic.point == pytest.approx((11.37492294352062, -18.060596519236338))
    assert gtwo.systems[1].lines == ()
    assert gtwo.systems[1].point is not None


def test_high_probability_outlook_zip():
    (area,) = parse_gtwo_zip(gis_bytes("gtwo_20250926.zip")).systems
    assert (area.prob_2day, area.risk_2day, area.prob_7day, area.risk_7day) == (80, "high", 90, "high")
    assert area.point == pytest.approx((19.74381257620592, -73.07185350973951))


def test_outlook_zip_with_no_areas_is_empty():
    data = gis_bytes("gtwo_20261031.zip")
    empty = parse_gtwo_zip(_without(data, "gtwo_areas"))
    assert empty.systems == ()
    assert empty.empty
    assert empty.issued == datetime(2026, 10, 31, 5, 7, tzinfo=UTC)
