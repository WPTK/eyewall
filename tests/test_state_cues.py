"""States that colour used to carry alone: the focused pane and the selected storm row also differ without colour."""

from __future__ import annotations

from eyewall.app import EyewallApp
from tests.ui_support import press, replay_app, running, screen_text


def _lines(app: EyewallApp) -> list[str]:
    return screen_text(app).splitlines()


async def test_the_focused_pane_has_a_heavy_border_and_the_others_a_round_one() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        storms = app.screen.query_one("#storms")
        app.screen.set_focus(storms)
        await press(pilot)
        top = _lines(app)[1]  # under the top bar
        assert top.startswith("┏━ Storms"), top  # the storm list is focused: heavy
        assert "╭" in top  # the map pane beside it is blurred: round
        await press(pilot, "tab")
        top = _lines(app)[1]
        assert top.startswith("╭─ Storms"), top  # focus left the storm list: round again
        assert "┏" in top  # and sits on another pane


async def test_the_selected_storm_row_is_underlined_and_the_others_are_not() -> None:
    app = replay_app()
    async with running(app, (140, 45)):
        strips = app.screen._compositor.render_strips()
        lines = [s.text for s in strips]
        selected = next(i for i, text in enumerate(lines) if "H3  ERIN" in text)
        header = next(i for i, text in enumerate(lines) if "ATLANTIC" in text)

        def underlined(row: int) -> bool:
            return any(seg.style and seg.style.underline for seg in strips[row] if seg.text.strip())

        assert underlined(selected)
        assert not underlined(header)
