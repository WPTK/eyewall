import gzip
from datetime import UTC, datetime

import pytest

from eyewall.models.wind import QuadrantRadii
from eyewall.providers.base import ParseError
from eyewall.providers.nhc.atcf import parse_bdeck, parse_btk_index
from tests.nhc_fixtures import nhc_bytes, nhc_text


def _fix_at(track, *args):
    when = datetime(*args, tzinfo=UTC)
    return next(f for f in track.fixes if f.time == when)


def test_erin_final_bdeck_from_the_archive_is_gzipped_and_starts_as_an_invest():
    raw = nhc_bytes("atcf/bal052025.dat.gz")
    assert raw[:2] == b"\x1f\x8b"
    track = parse_bdeck(raw)
    assert (track.basin_code, track.number) == ("AL", 5)
    assert len(track.fixes) == 68
    assert track.skipped == 0
    assert not track.is_invest
    first = track.fixes[0]
    assert first.time == datetime(2025, 8, 11, 0, 0, tzinfo=UTC)
    assert (first.lat, first.lon, first.vmax_kt, first.mslp_mb, first.type) == (16.5, -23.1, 30, 1007, "TD")
    assert first.name == "INVEST"
    assert track.name == "ERIN"  # the newest real name, not the INVEST placeholder
    assert track.latest.time == datetime(2025, 8, 27, 18, 0, tzinfo=UTC)
    assert (track.latest.type, track.latest.name) == ("EX", "ERIN")


def test_the_same_file_decompressed_and_as_text_parses_identically():
    raw = nhc_bytes("atcf/bal052025.dat.gz")
    plain = gzip.decompress(raw)
    assert parse_bdeck(plain) == parse_bdeck(raw) == parse_bdeck(plain.decode())


def test_three_lines_per_time_merge_into_one_fix_with_all_radii():
    track = parse_bdeck(nhc_bytes("atcf/bal052025.dat.gz"))
    assert len({f.time for f in track.fixes}) == len(track.fixes)  # one fix per time
    merged = _fix_at(track, 2025, 8, 15, 12)
    assert merged.radii.kt34 == QuadrantRadii(ne=100, se=50, sw=20, nw=90)
    assert merged.radii.kt50 == QuadrantRadii(ne=40, se=30, sw=0, nw=40)
    assert merged.radii.kt64 == QuadrantRadii(ne=20, se=0, sw=0, nw=0)


def test_early_rows_have_only_the_radii_lines_that_exist():
    track = parse_bdeck(nhc_bytes("atcf/bal052025.dat.gz"))
    early = _fix_at(track, 2025, 8, 11, 6)
    assert early.radii.kt34 == QuadrantRadii(ne=0, se=0, sw=0, nw=30)
    assert early.radii.kt50 is None
    assert early.radii.kt64 is None
    assert (early.direction_deg, early.speed_kt) == (0, 0)  # DIR and SPEED are often 0 in early rows


def test_peak_intensity_and_other_fields():
    track = parse_bdeck(nhc_bytes("atcf/bal052025.dat.gz"))
    peak = max(track.fixes, key=lambda f: f.vmax_kt or 0)
    assert peak.time == datetime(2025, 8, 16, 18, 0, tzinfo=UTC)
    assert (peak.vmax_kt, peak.type, peak.name) == (140, "HU", "ERIN")
    assert peak.pouter_mb is not None
    assert peak.router_nm is not None


def test_zero_means_unknown_for_pressure_and_wind():
    # The CP system's first rows carry pressure 0 in the file.
    track = parse_bdeck(nhc_bytes("atcf/bcp032026.dat"))
    first = track.fixes[0]
    assert first.mslp_mb is None
    assert first.vmax_kt == 20
    assert first.type == "DB"


def test_east_longitudes_and_the_dateline_crossing():
    track = parse_bdeck(nhc_bytes("atcf/bcp032026.dat"))
    assert (track.basin_code, track.number) == ("CP", 3)
    assert [f.lon for f in track.fixes[:3]] == [177.1, 177.6, 178.4]  # "1771E"
    crossing = [(f.time.isoformat(), f.lon) for f in track.fixes if f.lon > 179 or -180 < f.lon < -179]
    assert crossing[-2:] == [("2026-10-25T06:00:00+00:00", 179.6), ("2026-10-25T12:00:00+00:00", -179.6)]
    assert track.name == "OLANA"


def test_atlantic_post_tropical_low_and_a_pacific_storm():
    fay = parse_bdeck(nhc_bytes("atcf/bal062026.dat"))
    assert (fay.basin_code, fay.number, len(fay.fixes)) == ("AL", 6, 50)
    assert fay.fixes[0].name == "GENESIS017"
    assert fay.name == "FAY"
    assert fay.latest.type == "LO"
    vance = parse_bdeck(nhc_bytes("atcf/bep222026.dat"))
    assert (vance.basin_code, vance.number, vance.name) == ("EP", 22, "VANCE")
    assert vance.latest.time == datetime(2026, 10, 30, 0, 0, tzinfo=UTC)


def test_invest_and_training_numbers():
    text = nhc_text("atcf/bal062026.dat")
    invest = parse_bdeck(text.replace("AL, 06,", "AL, 94,"))
    training = parse_bdeck(text.replace("AL, 06,", "AL, 85,"))
    assert invest.is_invest and not invest.is_training
    assert training.is_training and not training.is_invest
    assert invest.number == 94


def test_short_garbled_and_foreign_lines_are_skipped_and_counted():
    text = nhc_text("atcf/bal062026.dat")
    lines = text.splitlines()
    damaged = [
        "AL, 06",  # too short
        "AL, 06, notadate,   , BEST,   0, 321N,  340W,  15, 1018, DB",  # bad date
        "AL, 06, 2026091712,   , BEST,   0, 321X,  340W,  15, 1018, DB",  # bad hemisphere
        lines[0].replace("BEST", "OFCL"),  # not a best track line
        "",
    ]
    track = parse_bdeck("\n".join(damaged + lines))
    assert len(track.fixes) == 50
    assert track.skipped == 4


def test_a_file_with_no_usable_rows_raises():
    for payload in (b"", b"<html>404</html>", b"AL, 06"):
        with pytest.raises(ParseError):
            parse_bdeck(payload)


def test_full_circle_radii_code_uses_the_first_radius():
    line = (
        "AL, 99, 2026090100,   , BEST,   0, 150N,  500W,  40, 1005, TS,  34, AAA,   60,    0,    0,    0, 1010,  200,"
        "  30,  50,   0,   L,   0,    ,   0,   0, TESTNAME, S"
    )
    fix = parse_bdeck(line).fixes[0]
    assert fix.radii.kt34 == QuadrantRadii(60, 60, 60, 60)
    assert (fix.lat, fix.lon, fix.rmw_nm, fix.gusts_kt, fix.name) == (15.0, -50.0, 30, 50, "TESTNAME")


# ---- btk directory listing ----------------------------------------------------------------------------------------


def test_btk_listing_names_every_2026_storm_file():
    files = parse_btk_index(nhc_bytes("atcf/btk_index.html"))
    assert len(files) == 35
    assert sorted((code, sum(1 for f in files if f.basin_code == code)) for code in ("AL", "CP", "EP")) == [
        ("AL", 10),
        ("CP", 3),
        ("EP", 22),
    ]
    assert all(f.year == 2026 for f in files)
    assert not any(f.is_invest or f.is_training for f in files)  # no invest files on the recorded quiet day
    olana = next(f for f in files if f.name == "bcp032026.dat")
    assert (olana.basin_code, olana.number, olana.storm_id) == ("CP", 3, "cp032026")
    assert olana.modified == datetime(2026, 10, 27, 2, 30, tzinfo=UTC)
    assert olana.size_bytes == 2662  # "2.6K"
    fay = next(f for f in files if f.storm_id == "al062026")
    assert fay.modified == datetime(2026, 9, 29, 20, 32, tzinfo=UTC)
    assert fay.size_bytes == 11 * 1024  # "11K"


def test_btk_listing_recognises_invest_files():
    html = '<a href="bal912026.dat">bal912026.dat</a>   2026-08-01 06:00  1.2K\n<a href="bal902026.dat">x</a> 2026-08-01 06:00 -\n'
    files = parse_btk_index(html)
    assert [(f.storm_id, f.is_invest) for f in files] == [("al912026", True), ("al902026", True)]
    assert files[1].size_bytes is None


def test_btk_listing_ignores_other_links():
    html = '<a href="cphc/">cphc/</a> 2014-07-08 23:42  -\n<a href="readme.txt">readme.txt</a> 2020-01-01 00:00 1K\n'
    assert parse_btk_index(html) == ()


def test_a_cut_off_gzip_b_deck_is_a_parse_error():
    whole = gzip.compress(nhc_bytes("atcf/bep222026.dat"))
    for cut in (whole[:4], whole[:40], whole[:-8]):
        with pytest.raises(ParseError):
            parse_bdeck(cut)


def test_a_b_deck_that_inflates_past_the_cap_is_a_parse_error(monkeypatch):
    monkeypatch.setattr("eyewall.providers.nhc.atcf.MAX_BDECK_BYTES", 1000)
    with pytest.raises(ParseError, match="larger than"):
        parse_bdeck(gzip.compress(b"x" * 5000))
