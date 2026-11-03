"""The canvas-to-strip conversion keeps every emphasis that survives NO_COLOR."""

import pytest
from textual.color import Color
from textual.filter import NoColor

from eyewall.render.canvas import Canvas, Mode, Style
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


@pytest.mark.parametrize("mode", list(Mode))
def test_the_app_background_is_gone_with_no_colour_in_every_mode(mode: Mode) -> None:
    """Strips always carry the app's background; Textual's NO_COLOR filter must still leave no colour in any mode."""
    canvas = Canvas(6, 2, mode=mode)
    canvas.text(0, 0, "ab", "#ffffff", bold=True)
    strips = canvas_strips(canvas, 6)
    assert all(seg.style is not None and seg.style.bgcolor is not None for strip in strips for seg in strip)
    for strip in strips:
        for seg in NoColor().apply(list(strip), Color.parse("black")):
            assert seg.style is not None
            assert seg.style.color.is_default and seg.style.bgcolor.is_default
