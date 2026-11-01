"""The hit map: which marks draw_scene reports in which cells, and how a cell, a near miss and the keyboard find them."""

from dataclasses import replace

from eyewall.geo import haversine_nm
from eyewall.render.canvas import Canvas, Mode
from eyewall.render.hits import Hits, Mark
from eyewall.render.layers import MapOptions, MapScene, StationMark, StormScene, TrackPoint, draw_scene
from eyewall.render.projection import Viewport
from tests.render_support import erin_like_scene

VIEW = Viewport(32.0, -66.0, 0.16, 120, 40)
STORM = Mark("storm", "AL052025")


def drawn(scene: MapScene, options: MapOptions | None = None, view: Viewport = VIEW) -> Hits:
    canvas = Canvas(view.cols, view.rows, Mode.BRAILLE)
    return draw_scene(canvas, view, scene, options or MapOptions())


def test_every_mark_on_the_canvas_has_a_cell() -> None:
    scene = erin_like_scene()
    hits = drawn(scene)
    assert {m for m, _ in hits.drawn} == {
        STORM,
        *(Mark("buoy", b.id) for b in scene.buoys),
        *(Mark("gauge", g.id) for g in scene.tide_gauges),
    }
    for mark, (col, row) in hits.drawn:
        assert mark in hits.at(col, row)  # the cell that holds a mark finds it


def test_the_cell_is_where_the_glyph_is_drawn() -> None:
    scene = erin_like_scene()
    canvas = Canvas(VIEW.cols, VIEW.rows, Mode.BRAILLE)
    hits = draw_scene(canvas, VIEW, scene, MapOptions())
    col, row = hits.cell_of(Mark("buoy", "41010")) or (-1, -1)
    assert canvas.cell(col, row)[0] == canvas.glyphs.buoy
    col, row = hits.cell_of(STORM) or (-1, -1)
    assert canvas.cell(col, row)[0] == canvas.glyphs.center


def test_a_layer_that_is_off_has_no_marks() -> None:
    hits = drawn(erin_like_scene(), MapOptions(buoys=False, tide_gauges=False))
    assert {m.kind for m, _ in hits.drawn} == {"storm"}


def test_marks_off_the_canvas_are_left_out() -> None:
    far = replace(erin_like_scene(), buoys=(StationMark(0.0, 20.0, id="FAR"),))
    assert Mark("buoy", "FAR") not in {m for m, _ in drawn(far).drawn}


def test_a_near_miss_within_one_cell_hits_but_two_cells_away_does_not() -> None:
    hits = Hits(((Mark("buoy", "A"), (10, 10)),), (Mark("buoy", "A"),))
    assert hits.at(10, 10) == (Mark("buoy", "A"),)
    assert hits.at(11, 9) == (Mark("buoy", "A"),)
    assert hits.at(12, 10) == ()
    assert hits.at(10, 12) == ()
    assert hits.at(12, 10, tolerance=2) == (Mark("buoy", "A"),)


def test_the_closest_marks_win_and_a_tie_keeps_all_of_them_topmost_first() -> None:
    a, b, c = Mark("storm", "S"), Mark("buoy", "B"), Mark("gauge", "G")
    hits = Hits(((a, (5, 5)), (b, (5, 5)), (c, (6, 5))), (a, b, c))
    assert hits.at(5, 5) == (a, b)  # two share the cell; the gauge beside it is not offered
    assert hits.at(6, 5) == (c,)
    assert hits.at(7, 5) == (c,)
    assert Hits(((b, (4, 5)), (c, (6, 5))), (b, c)).at(5, 5) == (b, c)  # equally close: both


def test_overlapping_marks_are_listed_with_the_storm_on_top() -> None:
    scene = MapScene(
        storms=(StormScene(id="S", center=TrackPoint(30.0, -70.0, 80.0)),),
        buoys=(StationMark(30.0, -70.0, 10.0, id="B"),),
        tide_gauges=(StationMark(30.0, -70.0, id="G"),),
    )
    hits = drawn(scene)
    col, row = hits.cell_of(Mark("storm", "S")) or (-1, -1)
    assert hits.at(col, row) == (Mark("storm", "S"), Mark("buoy", "B"), Mark("gauge", "G"))


def test_the_keyboard_visits_storms_then_stations_nearest_the_storm_first() -> None:
    hits = drawn(erin_like_scene())
    assert hits.order[0] == STORM
    assert len(hits.order) == len({m for m, _ in hits.drawn})
    scene = erin_like_scene()
    storm = scene.storms[0].center
    assert storm is not None
    by_id = {s.id: s for s in (*scene.buoys, *scene.tide_gauges)}
    miles = [haversine_nm((storm.lat, storm.lon), (by_id[m.id].lat, by_id[m.id].lon)) for m in hits.order[1:]]
    assert miles == sorted(miles)


def test_step_wraps_and_starts_at_either_end() -> None:
    a, b, c = Mark("storm", "S"), Mark("buoy", "B"), Mark("gauge", "G")
    hits = Hits((), (a, b, c))
    assert hits.step(None, 1) == a
    assert hits.step(None, -1) == c
    assert hits.step(a, 1) == b
    assert hits.step(c, 1) == a
    assert hits.step(a, -1) == c
    assert hits.step(Mark("buoy", "gone"), 1) == a
    assert Hits().step(None, 1) is None
