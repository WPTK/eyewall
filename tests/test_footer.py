"""The bottom row lists only the keys that work where the focus is, and never loses `? help`."""

from __future__ import annotations

import pytest
from rich.text import Text
from textual.widgets import TabbedContent

from eyewall.poll import Freshness, FreshnessState
from eyewall.ui import format as fmt
from eyewall.ui.screens.buoy_detail import BuoyDetailScreen
from eyewall.ui.screens.dashboard import DashboardScreen
from eyewall.ui.screens.detail import TABS
from tests.ui_support import into_the_storm, press, replay_app, running, screen_text, settle

SIZES = [(80, 24), (140, 45)]


def bottom(app) -> str:  # type: ignore[no-untyped-def]
    return screen_text(app).splitlines()[-1]


async def show_tab(pilot, tab: str) -> str:  # type: ignore[no-untyped-def]
    """Jump to a detail tab and return the bottom row once the footer has followed."""
    await pilot.press(str(([t for t, _ in TABS].index(tab) + 1) % 10))
    await pilot.pause()
    return bottom(pilot.app)


def one_row(app, width: int) -> str:  # type: ignore[no-untyped-def]
    """The bottom row: the screen's status widget is one row high, fits the width and ends with `? help`."""
    status = app.screen.query(".status-row, #status, #detail-status, #watch-status")
    assert all(widget.region.height == 1 for widget in status)
    row = bottom(app)
    assert len(row) <= width, row
    assert row.endswith("? help"), row
    return row


# ---- the row itself -------------------------------------------------------------------------------------------


def fixed(text: str):  # type: ignore[no-untyped-def]
    """A status that ignores the room it is given, to test the row on its own."""
    return lambda room: Text(text)


KEYS = [("enter", "detail"), ("b", "buoys"), ("m", "map")]


def test_keys_fill_the_room_whole_and_help_stays_last() -> None:
    status = fixed(" ● sources ok")
    wide = fmt.footer_row(status, KEYS, 80)
    assert len(wide.plain) == 80 and wide.plain.startswith(" ● sources ok  ")
    assert wide.plain.endswith("  enter detail  b buoys  m map  ? help")
    narrow = fmt.footer_row(status, KEYS, 58)  # room for two keys and no more
    assert narrow.plain.endswith("enter detail  b buoys  ? help") and "m map" not in narrow.plain
    assert len(narrow.plain) == 58
    bare = fmt.footer_row(status, KEYS, 30)
    assert bare.plain == " ● sources ok" + " " * 11 + "? help"


def test_the_key_set_does_not_depend_on_the_status_text() -> None:
    for width in range(70, 130):
        keys = {
            tuple(label for _, label in KEYS if label in fmt.footer_row(fixed(text), KEYS, width).plain)
            for text in ("", "next 9s", "next 10m 5s", "x" * 300)
        }
        assert len(keys) == 1, (width, keys)


def test_a_long_status_is_cut_before_the_keys_and_help() -> None:
    row = fmt.footer_row(fixed("x" * 200), [("b", "buoys")], 60)
    assert len(row.plain) == 60
    assert row.plain.endswith("b buoys  ? help")


def test_the_status_is_asked_for_the_room_the_keys_leave() -> None:
    rooms: list[int] = []
    fmt.footer_row(lambda room: rooms.append(room) or Text(""), KEYS, 100)  # type: ignore[func-returns-value]
    assert rooms == [100 - len("enter detail  b buoys  m map  ? help") - 2]


def test_wide_characters_are_measured_in_cells_not_characters() -> None:
    keys = [("w", "台風"), ("b", "buoys")]  # two characters, four cells
    row = fmt.footer_row(fixed("あ" * 30), keys, 40)
    assert row.cell_len == 40 and row.plain.endswith("? help")
    fits = fmt.footer_row(fixed("ok"), keys, 40)  # 24 reserved + "w 台風  " (8) + "? help" (6) + 2 = 40
    assert fits.cell_len == 40 and "台風" in fits.plain and "buoys" not in fits.plain


def test_the_footer_marks_keys_without_colour() -> None:
    row = fmt.footer_row(fixed(""), [("b", "buoys")], 50)
    styles = {str(span.style) for span in row.spans}
    assert styles == {"bold", "dim"}


@pytest.mark.parametrize(
    ("binding", "shown"), [("escape", "esc"), ("question_mark", "?"), ("plus,equals_sign", "+"), ("enter", "enter")]
)
def test_key_names_are_short(binding: str, shown: str) -> None:
    assert fmt.key_name(binding) == shown


# ---- the dashboard --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("size", SIZES)
async def test_dashboard_footer_is_one_row_and_follows_the_focus(size: tuple[int, int]) -> None:
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        seen = {}
        for _ in range(6):
            await pilot.pause()
            row = one_row(app, size[0])
            seen.setdefault(type(app.focused).__name__, row)
            await pilot.press("tab")
        assert "enter detail" in seen["StormList"]
        if size[0] >= 110:  # the map is on screen
            assert "+/- zoom" in seen["DashboardMap"] and seen["DashboardMap"] != seen["StormList"]


async def test_dashboard_map_lists_its_own_keys_and_the_list_does_not() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await into_the_storm(pilot)
        in_list = [label for _, label in app.footer_keys(app.screen)]
        assert in_list == ["detail", "buoys", "map"]
        app.screen.map_view.focus()
        await pilot.pause()
        assert "zoom" in bottom(app) and "center" in bottom(app) and "layers" in bottom(app)
        assert [label for _, label in app.footer_keys(app.screen)][:4] == ["zoom", "fit", "center", "layers"]


async def test_footer_follows_the_focus_without_waiting_for_the_clock() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await into_the_storm(pilot)
        before = bottom(app)
        app.screen.map_view.focus()
        await pilot.pause()  # no refresh_status call and no one-second pulse in between
        assert bottom(app) != before and "zoom" in bottom(app)


async def test_the_narrow_dashboard_tabs_list_the_same_keys_as_the_list() -> None:
    app = replay_app()
    async with running(app, (100, 30)) as pilot:
        await into_the_storm(pilot)
        app.screen.query_one("#side-tabs", TabbedContent).focus()
        await pilot.pause()
        assert [label for _, label in app.footer_keys(app.screen)] == ["detail", "buoys", "map"]
        one_row(app, 100)


# ---- the storm detail tabs ------------------------------------------------------------------------------------


@pytest.mark.parametrize("size", SIZES)
async def test_every_detail_tab_keeps_one_row_and_lists_only_working_keys(size: tuple[int, int]) -> None:
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        await pilot.press("enter")
        await pilot.pause()
        rows = {}
        for tab, _ in TABS:
            await show_tab(pilot, tab)
            one_row(app, size[0])
            rows[tab] = [label for _, label in app.footer_keys(app.screen)]
        assert "tcp/tcm" in rows["public"]
        assert not any("tcp/tcm" in labels for tab, labels in rows.items() if tab != "public")
        assert all(("pin" in labels) == (tab in ("buoys", "tides")) for tab, labels in rows.items())
        assert all(("charts" in labels) == (tab == "buoys") for tab, labels in rows.items())
        assert "open" in rows["graphics"] and "copy URL" in rows["graphics"]
        assert all("back" in labels for labels in rows.values())
        assert len({tuple(labels) for labels in rows.values()}) > 3  # it changes with the tab


async def test_keys_that_are_not_listed_do_nothing() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await into_the_storm(pilot)
        await pilot.press("enter")
        await pilot.pause()
        screen = app.screen
        await show_tab(pilot, "summary")
        before, toasts = screen.show_tcm, len(app._notifications)
        await pilot.press("t")
        await pilot.press("p")
        await pilot.pause()
        assert screen.show_tcm is before
        assert screen.query_one("#detail-tabs", TabbedContent).active == "tab-summary"
        assert len(app._notifications) == toasts
        await show_tab(pilot, "public")
        await pilot.press("t")
        assert screen.show_tcm is not before


async def test_a_tide_gauge_row_lists_no_enter() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await into_the_storm(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await show_tab(pilot, "tides")
        assert "charts" not in bottom(app) and "pin" in bottom(app)


# ---- other screens --------------------------------------------------------------------------------------------


async def test_the_watchlist_lists_its_keys_in_the_footer_not_in_its_header() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await pilot.press("w")
        await pilot.pause()
        row = one_row(app, 140)
        for text in ("a add", "d remove", "tab other table", "esc back", "enter charts"):
            assert text in row, row
        assert "Enter: charts" not in screen_text(app)


async def test_the_buoy_charts_list_range_pin_and_back() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await into_the_storm(pilot)
        app.open_buoy("41002")
        for _ in range(50):  # until the buoy screen is up
            await pilot.pause()
            if isinstance(app.screen, BuoyDetailScreen):
                break
        await pilot.pause()
        row = one_row(app, 140)
        assert "h range" in row and "p pin" in row and "esc back" in row


# ---- the crowded worst case -----------------------------------------------------------------------------------


@pytest.mark.parametrize("width", [70, 80, 90, 110])
async def test_help_survives_a_crowded_status_at_every_width(width: int) -> None:
    app = replay_app()
    async with running(app, (width, 24)) as pilot:
        app.poller.freshness = lambda feed: Freshness(FreshnessState.STALE, age=7500.0)  # type: ignore[method-assign]
        app.poller.active = lambda feed: True  # type: ignore[method-assign]
        app.alert_log = [object()] * 12  # type: ignore[list-item]
        app.screen.refresh_status()  # type: ignore[attr-defined]
        await pilot.pause()
        row = one_row(app, width)
        assert app.status_text(width, app.screen).plain.strip() == row.strip()  # redrawn from the crowded state
        assert "enter detail" in row


async def test_no_footer_below_the_help_threshold() -> None:
    app = replay_app()
    async with running(app, (69, 24)) as pilot:
        await pilot.pause()
        assert "? help" not in bottom(app) and "detail" not in bottom(app)


@pytest.mark.parametrize("size", [(80, 24), (100, 50), (120, 30), (200, 50), (280, 70)])
async def test_the_forecast_table_fits_without_scrolling_sideways(size: tuple[int, int]) -> None:
    from textual.widgets import DataTable

    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await show_tab(pilot, "forecast")
        table = app.screen.query_one("#forecast-table", DataTable)
        assert table.row_count > 5 and table.virtual_size.width <= table.size.width


@pytest.mark.parametrize("screen_key", ["g", "enter", "b"])
async def test_every_screen_rebuilds_its_footer_after_the_too_small_screen(screen_key: str) -> None:
    app = replay_app()
    async with running(app, (120, 30)) as pilot:
        await into_the_storm(pilot)
        await press(pilot, screen_key)
        assert not isinstance(app.screen, DashboardScreen)
        await pilot.resize_terminal(59, 24)
        await settle(pilot)
        await pilot.resize_terminal(60, 16)
        await settle(pilot)
        await pilot.resize_terminal(120, 30)
        await settle(pilot)
        assert one_row(app, 120).endswith("? help")
