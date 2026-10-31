"""Line charts: tick arithmetic, layout, gaps and golden renderings for one and two series."""

import math

import pytest

from eyewall.render.canvas import Mode
from eyewall.render.chart import (
    ChartSeries,
    ChartStyle,
    Tick,
    format_values,
    nice_step,
    nice_ticks,
    render_chart,
)
from tests.render_support import assert_golden

STYLE = ChartStyle()
BLUE, GREEN, ORANGE = "#4aa3ff", "#3ddc84", "#ffa63d"
HOURS = [Tick(-24, "-24h"), Tick(-18, "-18h"), Tick(-12, "-12h"), Tick(-6, "-6h"), Tick(0, "now")]


# The traces use only plain arithmetic so the goldens cannot depend on a platform's math library.
def pressure() -> tuple[tuple[float, float | None], ...]:
    return tuple(
        (-24 + i / 2, 1008 - max(0.0, 14 - abs(i - 34) * 0.7) + (0.4 if i % 3 == 0 else 0.0)) for i in range(49)
    )


def wind() -> tuple[tuple[float, float | None], ...]:
    return tuple((-24 + i / 2, None if 20 <= i <= 22 else 12 + max(0.0, 30 - abs(i - 34) * 2.5)) for i in range(49))


def gust() -> tuple[tuple[float, float | None], ...]:
    return tuple((x, None if y is None else y * 1.25) for x, y in wind())


def one_series(mode: Mode = Mode.BRAILLE):
    return render_chart([ChartSeries("pressure mb", pressure(), BLUE)], 50, 12, mode=mode, x_ticks=HOURS, title="41047")


def two_series():
    return render_chart(
        [ChartSeries("wind kt", wind(), GREEN), ChartSeries("gust kt", gust(), ORANGE)], 50, 12, x_ticks=HOURS
    )


# ------------------------------------------------------------------------------------------------------- ticks


@pytest.mark.parametrize(
    "span, target, step",
    [(10, 5, 2), (14.1, 5, 5), (100, 4, 50), (1, 5, 0.2), (0.05, 5, 0.01), (7, 5, 2), (1000, 5, 200), (3, 1, 5)],
)
def test_nice_steps_are_one_two_or_five_times_a_power_of_ten(span, target, step):
    assert nice_step(span, target) == pytest.approx(step)


def test_ticks_inside_the_range_by_default():
    values, step = nice_ticks(0.3, 9.7)
    assert step == 2 and values == [2, 4, 6, 8]


def test_covering_ticks_reach_past_the_data():
    values, step = nice_ticks(994.3, 1008.4, 5, cover=True)
    assert (values[0], values[-1], step) == (990, 1010, 5)


def test_a_flat_range_still_gets_ticks():
    values, _ = nice_ticks(5.0, 5.0)
    assert values[0] < 5.0 < values[-1] and 5.0 in values


def test_tick_labels_have_just_enough_decimals():
    assert format_values([0, 5, 10], 5) == ["0", "5", "10"]
    assert format_values([0.5, 1.0, 1.5], 0.5) == ["0.5", "1.0", "1.5"]
    assert format_values([0.001, 0.002], 0.001) == ["0.001", "0.002"]
    assert format_values([-0.0, 20.0], 20) == ["0", "20"]
    assert format_values([-5, 0, 5], 5) == ["-5", "0", "5"]


def test_floating_point_noise_does_not_leak_into_ticks():
    values, step = nice_ticks(0.0, 0.7, 7)
    assert values == [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]
    assert format_values(values, step)[3] == "0.3"


# ------------------------------------------------------------------------------------------------- goldens


def test_one_series_golden():
    assert_golden("chart_one_series_braille.txt", one_series().to_text())


def test_two_series_golden():
    assert_golden("chart_two_series_braille.txt", two_series().to_text())


def test_one_series_golden_in_ascii():
    canvas = one_series(Mode.ASCII)
    assert canvas.to_text().isascii()
    assert_golden("chart_one_series_ascii.txt", canvas.to_text())


def test_half_block_mode_draws_a_chart_too():
    text = one_series(Mode.HALF).to_text()
    assert "▀" in text or "▄" in text or "█" in text


# ----------------------------------------------------------------------------------------------- layout


def test_axes_labels_and_legend_are_where_a_reader_expects():
    lines = one_series().lines()
    assert lines[0].startswith("41047") and "■ pressure mb" in lines[0]
    assert lines[1].startswith("1010┤")  # the top tick label sits in the gutter, against the axis
    assert lines[-1].split() == ["-24h", "-18h", "-12h", "-6h", "now"]
    axis_row = lines[-2]
    assert axis_row.count("┬") == 5 and axis_row[4] == "└"
    gutter_cols = [line[:4] for line in lines[1:-2]]
    assert all(set(g) <= set(" 0123456789") for g in gutter_cols)  # y labels only, no plotted dots in the gutter


def test_x_tick_labels_are_centered_under_their_ticks_when_there_is_room():
    lines = one_series().lines()
    axis_row, label_row = lines[-2], lines[-1]
    tick_col = axis_row.index("┬", axis_row.index("┬") + 1)  # the second tick, -18h
    label_col = label_row.index("-18h")
    assert abs((label_col + 1) - tick_col) <= 1


def test_series_are_colored_and_the_legend_names_each_one():
    canvas = two_series()
    found = {canvas.cell(c, r)[1].fg for r in range(canvas.rows) for c in range(canvas.cols)}
    assert {GREEN, ORANGE} <= found
    assert canvas.lines()[0].startswith("■ wind kt  ■ gust kt")
    legend = [canvas.cell(c, 0) for c in range(canvas.cols)]
    assert ("■", (GREEN, None, False)) in legend and ("■", (ORANGE, None, False)) in legend


def test_a_gap_in_the_data_breaks_the_line():
    canvas = render_chart([ChartSeries("wind kt", wind(), GREEN)], 50, 12, x_ticks=HOURS, grid=False)
    # The plot starts at dot 6 (a two character gutter and the axis) and is 94 dots wide for 24 hours. Samples 20 to 22,
    # at -14, -13.5 and -13 hours, are missing, so the line stops after the sample at -14.5 (dot 43) and resumes at
    # -12.5 (dot 51).
    assert any(canvas.dot(43, y) for y in range(canvas.height)) and any(canvas.dot(51, y) for y in range(canvas.height))
    assert not any(canvas.dot(x, y) for x in range(45, 50) for y in range(canvas.height))


def test_nan_breaks_the_line_like_none():
    broken = tuple((x, math.nan if y is None else y) for x, y in wind())
    a = render_chart([ChartSeries("w", wind(), GREEN)], 50, 12, x_ticks=HOURS)
    b = render_chart([ChartSeries("w", broken, GREEN)], 50, 12, x_ticks=HOURS)
    assert a.to_text() == b.to_text()


def test_explicit_ranges_put_the_extremes_on_the_plot_edges():
    data = ((0.0, 10.0), (1.0, 30.0), (2.0, 20.0))
    canvas = render_chart([ChartSeries("", data, BLUE)], 30, 10, y_range=(10.0, 30.0), x_range=(0.0, 2.0), grid=False)
    # A two character gutter and the axis leave the plot dots 6 to 59 across, and its 8 rows are dots 0 to 31 down.
    assert canvas.dot(6, 31)  # x = 0, y = 10: the lower left corner
    assert canvas.dot(33, 0)  # x = 1, y = 30: the top, halfway across
    assert canvas.dot(59, 16)  # x = 2, y = 20: the right edge, halfway down


def test_data_range_default_stretches_the_axis_to_round_numbers():
    lines = one_series().lines()
    labels = [line.split("┤")[0].strip() for line in lines if "┤" in line]
    assert labels == ["1010", "1005", "1000", "995", "990"]


def test_given_y_ticks_are_used_as_they_are():
    ticks = [Tick(1000, "low"), Tick(1010, "high")]
    canvas = render_chart([ChartSeries("", pressure(), BLUE)], 40, 10, y_ticks=ticks, y_range=(995.0, 1010.0))
    text = canvas.to_text()
    assert "low┤" in text and "high┤" in text


def test_the_grid_can_be_turned_off():
    on = render_chart([ChartSeries("p", pressure(), BLUE)], 50, 12, x_ticks=HOURS)
    off = render_chart([ChartSeries("p", pressure(), BLUE)], 50, 12, x_ticks=HOURS, grid=False)

    def count(canvas):
        return sum(canvas.dot(x, y) for y in range(canvas.height) for x in range(canvas.width))

    assert count(on) > count(off) > 0
    grid_color = {on.cell(c, r)[1].fg for r in range(on.rows) for c in range(on.cols)}
    assert STYLE.grid in grid_color


def test_later_series_draw_over_earlier_ones():
    twin = ((0.0, 1.0), (1.0, 2.0))
    canvas = render_chart([ChartSeries("a", twin, BLUE), ChartSeries("b", twin, ORANGE)], 30, 10, grid=False)
    colors = {canvas.cell(c, r)[1].fg for r in range(1, canvas.rows - 2) for c in range(4, canvas.cols)}
    assert ORANGE in colors and BLUE not in colors


# ----------------------------------------------------------------------------------------- degenerate input


def test_an_empty_chart_is_just_axes():
    canvas = render_chart([], 30, 8)
    text = canvas.to_text()
    assert "└" in text and "┤" in text


def test_a_series_with_no_valid_points_is_just_axes():
    canvas = render_chart([ChartSeries("s", ((0.0, None), (1.0, math.nan)), BLUE)], 30, 8)
    assert "└" in canvas.to_text()


def test_a_flat_trace_and_a_single_point_still_draw():
    flat = render_chart([ChartSeries("s", ((0.0, 5.0), (1.0, 5.0), (2.0, 5.0)), BLUE)], 30, 10, grid=False)
    assert any(ch not in " │" for line in flat.lines()[1:-2] for ch in line[5:])
    single = render_chart([ChartSeries("s", ((3.0, 7.0),), BLUE)], 30, 10, grid=False)
    assert any(single.cell(c, r)[1].fg == BLUE for r in range(single.rows) for c in range(single.cols))


def test_a_tiny_canvas_does_not_raise():
    for cols, rows in [(1, 1), (3, 2), (8, 4), (6, 3)]:
        render_chart([ChartSeries("s", pressure(), BLUE)], cols, rows, title="t").to_text()


def test_ticks_outside_the_range_are_not_drawn():
    ticks = [Tick(-100, "far"), Tick(-12, "mid"), Tick(100, "away")]
    text = render_chart([ChartSeries("s", pressure(), BLUE)], 50, 12, x_ticks=ticks).to_text()
    assert "mid" in text and "far" not in text and "away" not in text


def test_crowded_x_labels_are_thinned_not_overlapped():
    ticks = [Tick(-24 + i, f"{i}h") for i in range(25)]
    last = render_chart([ChartSeries("s", pressure(), BLUE)], 50, 12, x_ticks=ticks).lines()[-1]
    words = last.split()
    assert 3 <= len(words) < 25 and all(w.endswith("h") for w in words)
