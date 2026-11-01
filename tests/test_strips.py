"""The canvas-to-strip conversion keeps every emphasis that survives NO_COLOR."""

from eyewall.render.canvas import Canvas, Style
from eyewall.ui.widgets.strips import canvas_strips, rich_style


def test_underline_and_reverse_reach_the_rich_style():
    style = rich_style(Style("#112233", None, True, True, True))
    assert style.bold and style.underline and style.reverse
    plain = rich_style(Style())
    assert not (plain.bold or plain.underline or plain.reverse)


def test_canvas_strips_carry_bold_from_the_canvas():
    canvas = Canvas(4, 1)
    canvas.text(0, 0, "ab", "#ffffff", bold=True)
    segments = [seg for strip in canvas_strips(canvas, 4) for seg in strip if seg.text.strip()]
    assert segments and all(seg.style.bold for seg in segments)
