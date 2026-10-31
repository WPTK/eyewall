"""The dot canvas: glyph encoding, lines, fills, priorities, text, clipping and output runs."""

import itertools
import math

import pytest

from eyewall.render.canvas import ASCII_GLYPHS, UNICODE_GLYPHS, Canvas, Mode, Priority, Shade, Style
from tests.render_support import assert_golden

RED, BLUE, GREEN = "#ff0000", "#0000ff", "#00ff00"


def dots(canvas: Canvas) -> set[tuple[int, int]]:
    return {(x, y) for y in range(canvas.height) for x in range(canvas.width) if canvas.dot(x, y)}


# -------------------------------------------------------------------------------------------------- glyph encoding


@pytest.mark.parametrize(
    "x, y, char",
    [(0, 0, "⠁"), (0, 1, "⠂"), (0, 2, "⠄"), (1, 0, "⠈"),
     (1, 1, "⠐"), (1, 2, "⠠"), (0, 3, "⡀"), (1, 3, "⢀")],
)  # fmt: skip
def test_each_braille_dot_has_its_unicode_bit(x, y, char):
    canvas = Canvas(1, 1)
    canvas.plot(x, y, RED)
    assert canvas.to_text() == char


def test_a_full_braille_cell_and_an_empty_one():
    canvas = Canvas(2, 1)
    for x in range(2):
        for y in range(4):
            canvas.plot(x, y, RED)
    assert canvas.to_text() == "⣿ "  # empty cells are plain spaces, not blank braille


def test_half_block_mode_has_one_by_two_dots():
    canvas = Canvas(3, 1, Mode.HALF)
    assert (canvas.width, canvas.height) == (3, 2)
    canvas.plot(0, 0, RED)
    canvas.plot(1, 1, RED)
    canvas.plot(2, 0, RED)
    canvas.plot(2, 1, RED)
    assert canvas.to_text() == "▀▄█"


def test_ascii_mode_uses_only_ascii():
    canvas = Canvas(3, 1, Mode.ASCII)
    canvas.plot(0, 0, RED)
    canvas.plot(1, 1, RED)
    canvas.plot(2, 0, RED)
    canvas.plot(2, 1, RED)
    assert canvas.to_text() == "'.:"
    assert canvas.glyphs is ASCII_GLYPHS
    assert Canvas(1, 1).glyphs is UNICODE_GLYPHS
    assert all(g.isascii() for g in vars(ASCII_GLYPHS).values())


def test_mode_dot_sizes():
    assert (Mode.BRAILLE.dots_x, Mode.BRAILLE.dots_y) == (2, 4)
    assert (Mode.HALF.dots_x, Mode.HALF.dots_y) == (1, 2)
    assert (Mode.ASCII.dots_x, Mode.ASCII.dots_y) == (1, 2)


def test_a_canvas_needs_a_cell():
    with pytest.raises(ValueError):
        Canvas(0, 3)


def test_plot_outside_the_canvas_is_ignored():
    canvas = Canvas(2, 2)
    for x, y in [(-1, 0), (0, -1), (4, 0), (0, 8), (100, 100)]:
        canvas.plot(x, y, RED)
    assert dots(canvas) == set()
    assert not canvas.dot(-1, -1) and not canvas.dot(99, 0)


# ------------------------------------------------------------------------------------------------------- lines


def test_horizontal_and_vertical_lines():
    canvas = Canvas(5, 2)
    canvas.line(0, 0, 9, 0, RED)
    assert canvas.lines()[0] == "⠉" * 5
    canvas = Canvas(1, 2)
    canvas.line(0, 0, 0, 7, RED)
    assert canvas.lines() == ["⡇", "⡇"]


def test_a_diagonal_covers_one_dot_per_step_and_reaches_both_ends():
    canvas = Canvas(4, 2)
    canvas.line(0, 0, 7, 7, RED)
    assert dots(canvas) == {(i, i) for i in range(8)}


def test_a_line_includes_its_end_points_in_either_direction():
    for a, b in [((1, 2), (13, 6)), ((13, 6), (1, 2)), ((3, 20), (11, 1))]:
        canvas = Canvas(8, 6)
        canvas.line(*a, *b, RED)
        assert canvas.dot(*a) and canvas.dot(*b)


def test_a_line_leaving_the_canvas_is_clipped_not_dropped():
    canvas = Canvas(10, 1)
    canvas.line(-100, 2, 500, 2, RED)
    assert dots(canvas) == {(x, 2) for x in range(20)}


def test_a_line_wholly_outside_draws_nothing():
    canvas = Canvas(10, 3)
    canvas.line(-50, -50, -10, 400, RED)
    canvas.line(30, 0, 30, 11, RED)
    assert dots(canvas) == set()


def test_a_huge_line_is_clipped_before_it_is_walked():
    canvas = Canvas(10, 3)
    canvas.line(-1e12, -1e12, 1e12, 1e12, RED)  # would never finish if every dot were visited
    found = dots(canvas)
    assert len(found) >= 12 and all(abs(x - y) <= 1 for x, y in found)  # still the diagonal, to within a dot


def test_non_finite_coordinates_are_ignored():
    canvas = Canvas(4, 2)
    canvas.line(0, 0, math.nan, 3, RED)
    canvas.line(0, 0, math.inf, 3, RED)
    canvas.polyline([(0, 0), (math.nan, math.nan), (3, 3)], RED)
    assert dots(canvas) == set()
    assert canvas.cell_of(math.nan, 1) is None


def test_a_dashed_line_alternates_on_and_off():
    canvas = Canvas(8, 1)
    canvas.line(0, 0, 11, 0, RED, dash=(2, 2))
    assert {x for x, _ in dots(canvas)} == {0, 1, 4, 5, 8, 9}


def test_a_dash_pattern_runs_on_across_the_joints_of_a_polyline():
    joined, single = Canvas(8, 1), Canvas(8, 1)
    joined.polyline([(0, 0), (5, 0), (11, 0)], RED, dash=(2, 2))
    single.line(0, 0, 11, 0, RED, dash=(2, 2))
    assert dots(joined) == dots(single)


def test_a_dash_pattern_keeps_its_phase_through_a_clipped_start():
    clipped, whole = Canvas(4, 1), Canvas(12, 1)
    clipped.line(-8, 0, 7, 0, RED, dash=(2, 2))
    whole.line(0, 0, 15, 0, RED, dash=(2, 2))
    assert {x for x, _ in dots(clipped)} == {x - 8 for x, _ in dots(whole) if x >= 8}


def test_width_two_doubles_the_stroke_across_the_line():
    canvas = Canvas(5, 2)
    canvas.line(0, 1, 9, 1, RED, width=2)
    assert {y for _, y in dots(canvas)} == {1, 2}
    canvas = Canvas(5, 2)
    canvas.line(2, 0, 2, 7, RED, width=2)
    assert {x for x, _ in dots(canvas)} == {2, 3}


def test_polyline_basics():
    canvas = Canvas(6, 3)
    canvas.polyline([(1, 1)], RED)
    assert dots(canvas) == {(1, 1)}
    canvas.polyline([], RED)
    square = Canvas(6, 3)
    square.polyline([(0, 0), (9, 0), (9, 9), (0, 9)], RED, closed=True)
    assert all(square.dot(x, y) for x, y in [(0, 5), (5, 0), (9, 5), (5, 9)])
    open_square = Canvas(6, 3)
    open_square.polyline([(0, 0), (9, 0), (9, 9), (0, 9)], RED)
    assert not open_square.dot(0, 5)


# --------------------------------------------------------------------------------------------------------- fills


def square_ring(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def test_a_rectangle_fills_the_dots_whose_centers_it_covers():
    canvas = Canvas(6, 3)
    canvas.fill_polygon([square_ring(2, 1, 8, 5)], RED)
    assert dots(canvas) == {(x, y) for x in range(2, 8) for y in range(1, 5)}


def test_winding_direction_does_not_matter():
    a, b = Canvas(6, 3), Canvas(6, 3)
    a.fill_polygon([square_ring(2, 1, 8, 5)], RED)
    b.fill_polygon([square_ring(2, 1, 8, 5)[::-1]], RED)
    assert dots(a) == dots(b)


def test_a_ring_inside_a_ring_is_a_hole():
    canvas = Canvas(6, 4)
    canvas.fill_polygon([square_ring(0, 0, 10, 10), square_ring(3, 3, 7, 7)], RED)
    assert len(dots(canvas)) == 100 - 16
    assert not canvas.dot(5, 5) and canvas.dot(1, 1)


def test_neighbouring_polygons_leave_no_gap_and_no_overlap():
    left, right, both = Canvas(8, 3), Canvas(8, 3), Canvas(8, 3)
    left.fill_polygon([square_ring(0.0, 0, 5.3, 6)], RED)
    right.fill_polygon([square_ring(5.3, 0, 11.0, 6)], RED)
    both.fill_polygon([square_ring(0.0, 0, 11.0, 6)], RED)
    assert dots(left) | dots(right) == dots(both)
    assert dots(left) & dots(right) == set()


def test_a_triangle_fills_about_its_area():
    canvas = Canvas(10, 6)
    canvas.fill_polygon([[(0, 0), (20, 0), (0, 20)]], RED)
    assert 190 <= len(dots(canvas)) <= 210
    assert canvas.dot(2, 2) and not canvas.dot(15, 15)


def test_a_fill_larger_than_the_canvas_is_clipped():
    canvas = Canvas(3, 2)
    canvas.fill_polygon([square_ring(-1000, -1000, 1000, 1000)], RED)
    assert len(dots(canvas)) == 6 * 8


def test_degenerate_rings_fill_nothing():
    canvas = Canvas(3, 2)
    canvas.fill_polygon([[(0, 0), (5, 5)], [(1, 1), (4, 4), (7, 7)], []], RED)
    canvas.fill_polygon([[(0, 0), (math.nan, 5), (5, 0)]], RED)
    assert dots(canvas) == set()


@pytest.mark.parametrize(
    "shade, count",
    [(Shade.SOLID, 64), (Shade.DENSE, 48), (Shade.HALF, 32), (Shade.SPARSE, 16), (Shade.LIGHT, 8),
     (Shade.HATCH_LIGHT, 8), (Shade.HATCH_MEDIUM, 16), (Shade.HATCH_HEAVY, 32)],
)  # fmt: skip
def test_shades_set_a_fixed_share_of_the_dots(shade, count):
    canvas = Canvas(4, 2)
    canvas.fill_polygon([square_ring(0, 0, 8, 8)], RED, shade=shade)
    assert len(dots(canvas)) == count


def test_shades_follow_the_dot_grid_so_neighbours_line_up():
    whole, parts = Canvas(8, 3), Canvas(8, 3)
    whole.fill_polygon([square_ring(0, 0, 16, 12)], RED, shade=Shade.HATCH_MEDIUM)
    parts.fill_polygon([square_ring(0, 0, 7, 12)], RED, shade=Shade.HATCH_MEDIUM)
    parts.fill_polygon([square_ring(7, 0, 16, 12)], RED, shade=Shade.HATCH_MEDIUM)
    assert dots(whole) == dots(parts)


# ---------------------------------------------------------------------------------------------- circles and arcs


def test_a_circle_stays_on_its_radius():
    canvas = Canvas(20, 10)
    canvas.circle(20, 20, 10, RED)
    found = dots(canvas)
    assert len(found) > 40
    assert all(abs(math.hypot(x + 0.5 - 20, y + 0.5 - 20) - 10) < 1.5 for x, y in found)
    assert {20, 30, 10} <= {x for x, _ in found} | {x for _, x in found}


def test_an_arc_covers_only_its_bearings():
    canvas = Canvas(20, 10)
    canvas.arc(20, 20, 10, 0, 90, RED)  # compass bearings: north round to east
    found = dots(canvas)
    assert found and all(x >= 19 and y <= 20 for x, y in found)
    back = Canvas(20, 10)
    back.arc(20, 20, 10, 90, 0, RED)
    assert dots(back) == dots(canvas)


def test_dashed_circle_has_fewer_dots_than_a_solid_one():
    solid, dashed = Canvas(20, 10), Canvas(20, 10)
    solid.circle(20, 20, 10, RED)
    dashed.circle(20, 20, 10, RED, dash=(3, 3))
    assert 0.3 < len(dots(dashed)) / len(dots(solid)) < 0.7


# --------------------------------------------------------------------------------------------- color and priority


def test_the_higher_priority_stroke_colors_the_cell_and_both_keep_their_dots():
    for order in ((0, 1), (1, 0)):
        canvas = Canvas(2, 1)
        strokes = [(RED, Priority.COAST, (0, 0)), (BLUE, Priority.TRACK, (1, 3))]
        for index in order:
            color, prio, (x, y) = strokes[index]
            canvas.plot(x, y, color, prio)
        assert canvas.cell(0, 0) == ("⢁", Style(BLUE))
        assert dots(canvas) == {(0, 0), (1, 3)}


def test_equal_priority_lets_the_later_stroke_win():
    canvas = Canvas(1, 1)
    canvas.plot(0, 0, RED, 5)
    canvas.plot(1, 0, BLUE, 5)
    canvas.plot(0, 1, GREEN, 4)
    assert canvas.cell(0, 0)[1].fg == BLUE


def test_track_over_warning_over_cone_over_coast():
    assert Priority.TRACK > Priority.WARNING > Priority.CONE > Priority.COAST > Priority.LAND


def test_a_filled_area_recolors_only_cells_it_outranks():
    canvas = Canvas(4, 2)
    canvas.line(0, 0, 7, 0, RED, Priority.TRACK)
    canvas.fill_polygon([square_ring(0, 0, 8, 8)], BLUE, Priority.CONE)
    assert {canvas.cell(c, 0)[1].fg for c in range(4)} == {RED}
    assert {canvas.cell(c, 1)[1].fg for c in range(4)} == {BLUE}


# ----------------------------------------------------------------------------------------------- text and markers


def test_text_replaces_the_cells_under_it():
    canvas = Canvas(6, 2)
    canvas.line(0, 0, 11, 0, RED)
    canvas.text(1, 0, "abc", GREEN)
    assert canvas.lines()[0] == "⠉abc⠉⠉"
    assert canvas.cell(2, 0) == ("b", Style(GREEN))


def test_text_is_clipped_at_the_canvas_edges():
    canvas = Canvas(4, 2)
    canvas.text(-2, 0, "abcdef", RED)
    canvas.text(2, 1, "xyz", RED)
    canvas.text(0, 5, "off", RED)
    canvas.text(0, -1, "off", RED)
    assert canvas.lines() == ["cdef", "  xy"]


def test_text_does_not_replace_text_of_a_higher_priority():
    canvas = Canvas(4, 1)
    canvas.text(0, 0, "aaaa", RED, Priority.CURSOR)
    canvas.text(1, 0, "bb", BLUE, Priority.LABEL)
    assert canvas.lines() == ["aaaa"]
    canvas.text(1, 0, "cc", BLUE, Priority.CURSOR)
    assert canvas.lines() == ["acca"]


def test_text_can_be_bold():
    canvas = Canvas(3, 1)
    canvas.text(0, 0, "hi", RED, bold=True)
    assert canvas.cell(0, 0)[1] == Style(RED, None, True)


def test_ascii_mode_replaces_characters_it_cannot_draw():
    canvas = Canvas(6, 1, Mode.ASCII)
    canvas.text(0, 0, "Año ◆", RED)
    assert canvas.to_text() == "A?o ? "
    assert canvas.to_text().isascii()


def test_text_free_reports_room_for_a_label():
    canvas = Canvas(8, 2)
    canvas.text(2, 0, "ab", RED)
    assert canvas.text_free(4, 0, 4)
    assert not canvas.text_free(0, 0, 3)  # runs into "ab"
    assert not canvas.text_free(6, 0, 3)  # runs off the edge
    assert not canvas.text_free(-1, 0, 2) and not canvas.text_free(0, 2, 1)
    canvas.line(0, 4, 15, 4, RED)
    assert canvas.text_free(0, 1, 8)  # dots do not block a label; only other text does


def test_marker_goes_in_the_cell_holding_a_dot_coordinate():
    canvas = Canvas(4, 2)
    assert canvas.marker(5.9, 4.2, "X", RED) == (2, 1)
    assert canvas.lines() == ["    ", "  X "]
    assert canvas.marker(-0.1, 0, "Y", RED) is None
    assert canvas.marker(8.0, 0, "Y", RED) is None


# ------------------------------------------------------------------------------------------------- output and misc


def test_runs_merge_neighbouring_cells_of_one_style():
    canvas = Canvas(8, 1)
    canvas.line(0, 0, 5, 0, RED)  # three red cells
    canvas.text(4, 0, "ab", BLUE)
    canvas.text(7, 0, "z", BLUE, bold=True)
    runs = canvas.rows_as_runs()[0]
    assert runs == [
        ("⠉⠉⠉ ", Style(RED)),  # the blank cell after the line joins the run before it
        ("ab ", Style(BLUE)),
        ("z", Style(BLUE, None, True)),
    ]
    assert "".join(text for text, _ in runs) == canvas.lines()[0]


def test_runs_cover_every_cell_exactly_once():
    canvas = Canvas(12, 4)
    canvas.circle(12, 8, 6, RED)
    canvas.text(3, 1, "label", GREEN)
    for runs, line in zip(canvas.rows_as_runs(), canvas.lines(), strict=True):
        assert "".join(text for text, _ in runs) == line
        assert all(a[1] != b[1] for a, b in itertools.pairwise(runs))


def test_a_blank_canvas_is_one_unstyled_run_per_row():
    assert Canvas(5, 2).rows_as_runs() == [[("     ", Style())], [("     ", Style())]]


def test_copy_is_independent():
    original = Canvas(4, 2)
    original.line(0, 0, 7, 0, RED)
    clone = original.copy()
    clone.line(0, 7, 7, 7, BLUE)
    clone.text(0, 0, "x", RED)
    assert dots(original) == {(x, 0) for x in range(8)}
    assert original.lines()[0] == "⠉" * 4
    assert clone.lines()[0].startswith("x")


def test_clipped_limits_dots_and_nests():
    canvas = Canvas(6, 3)
    with canvas.clipped(2, 2, 8, 8):
        canvas.line(0, 0, 11, 11, RED)
        with canvas.clipped(0, 0, 5, 5):  # an inner clip can only narrow the outer one
            canvas.plot(6, 6, BLUE)
            canvas.plot(4, 4, BLUE)
        canvas.fill_polygon([square_ring(0, 0, 12, 12)], GREEN, shade=Shade.SOLID)
    canvas.plot(0, 0, RED)  # restored on exit
    assert all(2 <= x < 8 and 2 <= y < 8 for x, y in dots(canvas) - {(0, 0)})
    assert canvas.dot(0, 0)
    assert len(dots(canvas)) == 6 * 6 + 1


def test_clip_restored_after_an_error():
    canvas = Canvas(3, 2)
    with pytest.raises(RuntimeError), canvas.clipped(0, 0, 1, 1):
        raise RuntimeError
    canvas.plot(5, 5, RED)
    assert canvas.dot(5, 5)


# -------------------------------------------------------------------------------------------------------- golden


def draw_shapes(canvas: Canvas) -> None:
    sx, sy = canvas.dots_x / 2, canvas.dots_y / 4  # shapes are laid out in braille dots and scaled for other modes
    ring = [(x * sx, y * sy) for x, y in [(4, 4), (36, 8), (30, 40), (8, 36)]]
    canvas.fill_polygon([ring], "#444444", Priority.LAND, Shade.HATCH_MEDIUM)
    canvas.polyline(ring, RED, Priority.COAST, closed=True)
    canvas.circle(56 * sx, 22 * sy, 14 * sy, BLUE, Priority.TRACK)
    canvas.arc(56 * sx, 22 * sy, 8 * sy, 45, 270, GREEN, Priority.TRACK)
    canvas.line(40 * sx, 4 * sy, 78 * sx, 6 * sy, RED, Priority.TRACK, dash=(4, 2))
    canvas.line(40 * sx, 42 * sy, 78 * sx, 30 * sy, RED, Priority.TRACK, width=2)
    canvas.fill_polygon(
        [[(62 * sx, 28 * sy), (76 * sx, 28 * sy), (76 * sx, 40 * sy), (62 * sx, 40 * sy)]], GREEN, shade=Shade.HALF
    )
    canvas.marker(56 * sx, 22 * sy, canvas.glyphs.center, RED)
    canvas.text(19, 2, "LABEL", GREEN)


@pytest.mark.parametrize("mode", list(Mode))
def test_shapes_render_the_same_everywhere(mode):
    canvas = Canvas(40, 11, mode)
    draw_shapes(canvas)
    assert_golden(f"canvas_shapes_{mode.value}.txt", canvas.to_text())
