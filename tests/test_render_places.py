"""Place names and the scale bar: the data file, the build step, the ranking by zoom, collisions and the bar."""

import importlib.util
import struct
import sys
from pathlib import Path

import pytest

from eyewall.mapdata import loader
from eyewall.mapdata.loader import Place, load_places, parse_places
from eyewall.palette import NEUTRAL
from eyewall.render import places as P
from eyewall.render.canvas import Canvas, Mode, Priority
from eyewall.render.layers import MapOptions, MapScene, StormScene, TrackPoint, render_map
from eyewall.render.projection import Viewport
from eyewall.units import PRESETS

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "build_mapdata.py"
DATA_DIR = Path(loader.__file__).parent
NO_BASE = MapOptions(land=False, coast=False, borders=False)
NO_BASE_NO_PLACES = MapOptions(land=False, coast=False, borders=False, places=False)


@pytest.fixture(scope="module")
def build():
    spec = importlib.util.spec_from_file_location("build_mapdata_places", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_mapdata_places"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("build_mapdata_places", None)


def place(name, lat, lon, rank=0, pop=1000, ascii_name=None):
    return Place(lat, lon, rank, pop, name, ascii_name or name)


def blank(cols=60, rows=20, mode=Mode.BRAILLE, deg=0.05):
    view = Viewport(30.0, -70.0, deg, cols, rows, mode.dots_x, mode.dots_y)
    return Canvas(cols, rows, mode), view


# ------------------------------------------------------------------------------------------------ the data file


def test_places_file_stays_within_its_budget_and_the_map_data_within_4_5_mb():
    assert (DATA_DIR / "places.bin").stat().st_size <= 150_000
    assert sum(path.stat().st_size for path in DATA_DIR.glob("*.bin")) <= 4_500_000


def test_places_are_ordered_most_important_first_and_known_places_are_present():
    places = load_places()
    assert 1_500 < len(places) < 4_000
    keys = [(p.scalerank, -p.population) for p in places]
    assert keys == sorted(keys)
    names = {p.name for p in places}
    for name in ("Miami", "Nassau", "Honolulu", "Havana", "Hamilton"):
        assert name in names, name
    assert all(-10.5 <= p.lat <= 65.5 for p in places)


def test_the_places_source_is_pinned_by_digest_and_documented(build):
    digest = build.SOURCE_SHA256[build.PLACES_SOURCE]
    assert len(digest) == 64 and build.PLACES_SOURCE == "ne_10m_populated_places_simple"
    attribution = (DATA_DIR / "ATTRIBUTION.md").read_text(encoding="utf-8")
    assert digest in attribution and "places.bin" in attribution and build.MIRROR_REF in attribution
    docs = (ROOT / "docs" / "data-sources.md").read_text(encoding="utf-8")
    assert "populated_places_simple" in docs and build.MIRROR_REF in docs


def feature(name="Bermuda Town", rank=3, lon=-64.7, lat=32.3, pop=5000):
    return {
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "name": name,
            "nameascii": name,
            "scalerank": rank,
            "pop_max": pop,
            "latitude": lat,
            "longitude": lon,
            "extra_field": "ignored",
        },
    }


def test_build_keeps_places_in_the_box_with_a_usable_rank_and_orders_them(build):
    collection = {
        "features": [
            feature("Small", 8, pop=10),
            feature("Big", 1, lat=25.0, lon=-80.0, pop=900),
            feature("Bigger", 1, lat=26.0, lon=-81.0, pop=950),
            feature("Village", 9),
            feature("FarSouth", 3, lat=-40.0, lon=-60.0),
            feature("Europe", 3, lat=48.0, lon=10.0),
            feature("Asia", 3, lat=35.0, lon=139.0),
            feature("Pacific", 3, lat=21.0, lon=-158.0),
            feature("", 3),
            {"properties": {"name": "NoPosition", "scalerank": 2}},
            {"properties": None},
        ]
    }
    names = [p[4] for p in build.places_from(collection)]
    assert names[:2] == ["Bigger", "Big"] and names[-1] == "Small"
    assert set(names) == {"Bigger", "Big", "Asia", "Pacific", "Small"}


def test_places_round_trip_through_the_binary_format_including_non_ascii_names(build):
    packed = [
        (-802089, 257753, 0, 5_000_000, "Miami", "Miami"),
        (-868300, 211700, 2, 700_000, "Cancún", "Cancun"),
        (1502500, -35000, 8, 0, "Z", "Z"),
    ]
    parsed = parse_places(build.pack_places(packed))
    assert [(p.name, p.name_ascii, p.scalerank, p.population) for p in parsed] == [
        ("Miami", "Miami", 0, 5_000_000),
        ("Cancún", "Cancun", 2, 700_000),
        ("Z", "Z", 8, 0),
    ]
    assert parsed[0].lat == pytest.approx(25.7753) and parsed[0].lon == pytest.approx(-80.2089)


def test_a_damaged_places_file_is_refused():
    good = (DATA_DIR / "places.bin").read_bytes()
    for bad in (good[:10], good[:2000], b"EWMD" + good[4:], good[:4] + bytes([9]) + good[5:], b""):
        with pytest.raises(ValueError):
            parse_places(bad)
    with pytest.raises(ValueError):
        parse_places(struct.pack("<4sBBHII", b"EWPL", 1, 0, 0, 0, 0))


# --------------------------------------------------------------------------------------------- ranking by zoom


@pytest.mark.parametrize(
    ("deg", "rank"),
    [(4.0, 2), (0.5, 2), (0.49, 4), (0.3, 4), (0.29, 6), (0.1, 6), (0.099, 8), (0.002, 8)],
)
def test_the_rank_cutoff_follows_the_zoom(deg, rank):
    assert P.max_rank(deg) == rank


def test_a_coarse_view_labels_only_the_great_places_and_a_close_one_adds_the_small():
    places = (
        place("Great", 30.0, -70.0, rank=2),
        place("Town", 30.3, -69.5, rank=6),
        place("Hamlet", 29.7, -70.5, rank=8),
    )
    seen = {}
    for deg in (0.6, 0.35, 0.2, 0.05):
        canvas, view = blank(120, 40, deg=deg)
        P.draw_places(canvas, view, NEUTRAL, places)
        text = canvas.to_text()
        seen[deg] = {name for name in ("Great", "Town", "Hamlet") if name in text}
    assert seen == {0.6: {"Great"}, 0.35: {"Great"}, 0.2: {"Great", "Town"}, 0.05: {"Great", "Town", "Hamlet"}}


def test_at_most_one_label_per_150_cells_and_the_most_important_places_win():
    assert P.label_limit(60, 20) == 8 and P.label_limit(2, 2) == 1
    places = tuple(
        sorted(
            (place(f"P{i:02d}", 30.0 + (i % 5) * 0.1, -70.0 + (i // 5) * 0.2, rank=i % 3) for i in range(30)),
            key=lambda p: p.scalerank,
        )
    )
    canvas, view = blank(60, 20, deg=0.01)
    assert P.draw_places(canvas, view, NEUTRAL, places) <= 8
    text = canvas.to_text()
    shown = [p for p in places if p.name in text]
    assert 1 <= len(shown) <= 8
    dropped = [p for p in places if p.name not in text]
    assert max(p.scalerank for p in shown) <= min(p.scalerank for p in dropped) or len(shown) == 8


# -------------------------------------------------------------------------------------------- collisions, glyphs


def test_a_lower_ranked_place_that_would_touch_a_label_is_dropped():
    places = (place("Important", 30.0, -70.0, rank=1), place("Minor", 30.0, -69.99, rank=5, pop=10))
    canvas, view = blank(60, 20, deg=0.05)
    assert P.draw_places(canvas, view, NEUTRAL, places) == 1
    text = canvas.to_text()
    assert "Important" in text and "Minor" not in text


def test_a_label_flips_to_the_left_at_the_right_edge_and_is_dropped_when_nothing_fits():
    canvas, view = blank(40, 12, deg=0.05)
    edge = view.to_geo(view.width - 2, view.height / 2)
    assert P.draw_places(canvas, view, NEUTRAL, (place("Eastern", edge[0], edge[1]),)) == 1
    row = next(line for line in canvas.lines() if "Eastern" in line)
    assert row.rstrip().endswith("Eastern·")
    tiny, small = blank(6, 4, deg=0.05)
    assert P.draw_places(tiny, small, NEUTRAL, (place("Much too long a name", 30.0, -70.0),)) == 0


def test_labels_keep_off_storm_markers_and_the_track():
    storm = StormScene(
        name="ERIN",
        center=TrackPoint(30.0, -70.0, 100.0),
        best_track=(TrackPoint(30.0, -72.0, 90.0), TrackPoint(30.0, -70.0, 100.0)),
    )
    view = Viewport(30.0, -70.0, 0.05, 60, 20)
    bare = render_map(view, MapScene(storms=(storm,)), options=NO_BASE_NO_PLACES)
    places = (place("OnTrack", 30.0, -71.0), place("AtCentre", 30.0, -70.0), place("Clear", 31.0, -69.0, rank=1))
    canvas = bare.copy()
    P.draw_places(canvas, view, NEUTRAL, places)
    text = canvas.to_text()
    assert "Clear" in text and "OnTrack" not in text and "AtCentre" not in text
    assert text.count("◉") == 1
    # every cell the labels changed lies in the one row of the label that was drawn
    changed = {r for r in range(canvas.rows) for c in range(canvas.cols) if bare.cell(c, r) != canvas.cell(c, r)}
    assert len(changed) == 1 and "Clear" in canvas.lines()[changed.pop()]


def test_place_labels_never_displace_an_existing_label():
    canvas, view = blank(60, 20, deg=0.05)
    col, row = canvas.cell_of(*view.to_dot(30.0, -70.0))
    canvas.text(col + 1, row, "STORM", "#ffffff", Priority.LABEL)
    P.draw_places(canvas, view, NEUTRAL, (place("Town", 30.0, -70.0),))
    assert "STORM" in canvas.to_text()


def test_ascii_mode_prints_ascii_names_and_wide_characters_fall_back():
    places = (place("São Paulo", 30.0, -70.0, ascii_name="Sao Paulo"), place("東京", 30.5, -69.0, ascii_name="Tokyo"))
    uni, view = blank(60, 20, deg=0.05)
    P.draw_places(uni, view, NEUTRAL, places)
    assert "São Paulo" in uni.to_text() and "Tokyo" in uni.to_text() and "東京" not in uni.to_text()
    asc, aview = blank(60, 20, Mode.ASCII, deg=0.1)
    P.draw_places(asc, aview, NEUTRAL, places)
    assert "Sao Paulo" in asc.to_text() and "·" not in asc.to_text() and asc.to_text().isascii()


def test_place_labels_are_text_so_they_read_with_no_color():
    canvas, view = blank(60, 20, deg=0.05)
    P.draw_places(canvas, view, None, (place("Miami", 30.0, -70.0),))
    assert "Miami" in canvas.to_text()


# ------------------------------------------------------------------------------------------------ scale bar


@pytest.mark.parametrize("unit", ["nm", "mi", "km"])
def test_the_scale_bar_length_matches_the_ground_distance_in_each_unit(unit):
    view = Viewport(30.0, -70.0, 0.05, 100, 30)
    distance, cells = P.scale_length(view, unit)
    per_cell = {"nm": 1.0, "mi": 1.150779, "km": 1.852}[unit] * 60 * 0.05 * 2
    assert distance > 0 and distance / 10 ** (len(str(distance)) - 1) in {1, 2, 5}
    assert cells == round(distance / per_cell) and P.SCALE_MIN_CELLS <= cells <= 100 // 3


def test_the_scale_bar_names_its_unit_from_the_preset():
    view = Viewport(30.0, -70.0, 0.05, 100, 30)
    for preset in PRESETS.values():
        canvas = Canvas(100, 30)
        assert P.draw_scale_bar(canvas, view, preset.distance, NEUTRAL)
        last = canvas.lines()[-1]
        assert last.lstrip().startswith("├") and last.rstrip().endswith(f" {preset.distance}")
    canvas = Canvas(100, 30)
    P.draw_scale_bar(canvas, view, "furlongs", NEUTRAL)  # an unknown unit falls back to nautical miles
    assert canvas.lines()[-1].rstrip().endswith(" nm")


def test_the_ascii_scale_bar_uses_ascii_only():
    view = Viewport(30.0, -70.0, 0.1, 80, 24, 1, 2)
    canvas = Canvas(80, 24, Mode.ASCII)
    P.draw_scale_bar(canvas, view, "mi", None)
    last = canvas.lines()[-1].strip()
    assert last.startswith("+-") and last.isascii() and last.endswith(" mi")


def test_the_scale_bar_moves_to_the_right_corner_and_is_skipped_when_both_are_taken_or_the_map_is_tiny():
    view = Viewport(30.0, -70.0, 0.05, 100, 30)
    canvas = Canvas(100, 30)
    canvas.text(2, 29, "X", None, Priority.MARKER)
    assert P.draw_scale_bar(canvas, view, "nm", None)
    assert canvas.lines()[-1].rstrip().endswith("nm") and canvas.lines()[-1].startswith("  X")
    canvas.text(97, 29, "Y", None, Priority.MARKER)
    assert not P.draw_scale_bar(canvas, view, "nm", None)
    assert not P.draw_scale_bar(Canvas(9, 5), Viewport(30.0, -70.0, 0.05, 9, 5), "nm", None)


def test_a_zoom_with_no_round_distance_that_fits_draws_nothing():
    assert P.scale_length(Viewport(30.0, -70.0, 0.05, 11, 5), "nm") == (0, 0)


# -------------------------------------------------------------------------------------------- through render_map


def test_render_map_draws_places_and_a_scale_bar_and_the_option_switches_both_off():
    view = Viewport(25.5, -80.0, 0.04, 100, 30)
    on = render_map(view, MapScene(distance_unit="km"), options=NO_BASE).to_text()
    assert "Miami" in on and " km" in on.splitlines()[-1] and "├" in on.splitlines()[-1]
    assert render_map(view, MapScene(), options=NO_BASE_NO_PLACES).to_text().strip() == ""


def test_the_storm_name_label_wins_over_a_place_in_the_same_spot():
    view = Viewport(25.77, -80.2, 0.04, 100, 30)
    scene = MapScene(storms=(StormScene(name="ERIN", center=TrackPoint(25.77, -80.2, 100.0)),))
    text = render_map(view, scene, options=NO_BASE).to_text()
    assert "ERIN" in text and text.count("◉") == 1
