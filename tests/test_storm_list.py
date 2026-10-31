"""The storm list widget alone: rebuilds must not look like the user picking a row."""

from __future__ import annotations

from rich.text import Text
from textual.app import App, ComposeResult

from eyewall.ui.format import Row
from eyewall.ui.widgets.storm_list import StormList


def _rows(first: str = "A one") -> list[Row]:
    return [
        Row("header", "h", Text("ATLANTIC")),
        Row("storm", "al01", Text(first)),
        Row("storm", "al02", Text("B two")),
    ]


class ListApp(App[None]):
    def __init__(self) -> None:
        super().__init__()
        self.picked: list[str] = []

    def compose(self) -> ComposeResult:
        yield StormList(id="storms")

    def on_storm_list_picked(self, event: StormList.Picked) -> None:
        self.picked.append(event.row_id)


async def test_a_rebuild_does_not_emit_a_pick_or_move_the_selection() -> None:
    app = ListApp()
    async with app.run_test() as pilot:
        storms = app.query_one(StormList)
        assert storms.set_rows(_rows(), "al02") == "al02"
        await pilot.pause()
        await pilot.pause()
        app.picked.clear()
        selected = storms.set_rows(_rows("A one, changed"), "al02")  # the text differs: the options are rebuilt
        for _ in range(4):
            await pilot.pause()
        assert selected == "al02"
        assert app.picked == []
        assert storms.highlighted_row is not None
        assert storms.highlighted_row.id == "al02"


async def test_moving_the_cursor_still_picks() -> None:
    app = ListApp()
    async with app.run_test() as pilot:
        storms = app.query_one(StormList)
        storms.set_rows(_rows(), "al01")
        await pilot.pause()
        await pilot.pause()
        app.picked.clear()
        storms.action_cursor_down()
        await pilot.pause()
        await pilot.pause()
        assert app.picked == ["al02"]
