"""The Textual features the app relies on exist in the installed version and behave as expected."""

import importlib.util

from rich.segment import Segment
from rich.style import Style
from textual.app import App, ComposeResult
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import DataTable, Sparkline, TabbedContent


class Ruler(ScrollView):
    """A line-oriented widget like the map: it paints each row itself through render_line."""

    def __init__(self) -> None:
        super().__init__()
        self.virtual_size = Size(40, 3)

    def render_line(self, y: int) -> Strip:
        return Strip([Segment(f"row {y}".ljust(40), Style(color="green"))])


class RulerApp(App[None]):
    def compose(self) -> ComposeResult:
        yield Ruler()


async def test_render_line_widget_renders_in_a_test_app():
    app = RulerApp()
    async with app.run_test(size=(50, 10)) as pilot:
        await pilot.pause()
        ruler = app.query_one(Ruler)
        assert ruler.render_line(1).text.startswith("row 1")


def test_widgets_the_ui_plans_to_use_are_present():
    assert all(widget is not None for widget in (DataTable, Sparkline, TabbedContent))


def test_snapshot_plugin_is_installed():
    assert importlib.util.find_spec("pytest_textual_snapshot") is not None
