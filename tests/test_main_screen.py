"""The main screen: the map is the largest thing at every size, the cards and lists drop whole items, a click on a storm
opens it, and the nothing-active state says so."""

from __future__ import annotations

import pytest
from rich.cells import cell_len
from rich.text import Text
from textual.widget import Widget

from eyewall.app import EyewallApp
from eyewall.ui.screens.main import LARGE_FROM, MEDIUM_FROM, MainScreen, Tier, tier_for
from eyewall.ui.screens.storm import StormScreen
from eyewall.ui.widgets.map_view import MapView
from eyewall.ui.widgets.side_panel import Block, Line, SidePanel, fit_blocks, heading, wrapped
from tests.ui_support import into_the_storm, press, replay_app, running, screen_text, scripted_app, settle

SIZES = [(80, 24), (100, 40), (200, 50)]


def block(rows: int, priority: int = 0, **kwargs: object) -> Block:
    return Block(tuple(Line(Text(f"row {i}")) for i in range(rows)), priority, **kwargs)  # type: ignore[arg-type]


def shown(lines: list[Line]) -> list[str]:
    return [line.text.plain for line in lines]


# ---- the pure layout ----------------------------------------------------------------------------------------------


def test_the_tier_follows_the_size() -> None:
    assert tier_for(80, 24) is Tier.SMALL
    assert tier_for(99, 50) is Tier.SMALL  # too narrow for a column
    assert tier_for(200, 29) is Tier.SMALL  # too short for one
    assert tier_for(*MEDIUM_FROM) is Tier.MEDIUM
    assert tier_for(159, 60) is Tier.MEDIUM
    assert tier_for(*LARGE_FROM) is Tier.LARGE


def test_wrapped_breaks_on_words_and_never_cuts_one() -> None:
    lines = shown(wrapped("alpha beta gamma delta", 12, prefix="> "))
    assert all(cell_len(t) <= 12 for t in lines)
    assert " ".join(t.removeprefix(">").strip() for t in lines) == "alpha beta gamma delta"
    assert shown(wrapped("a-very-long-unbreakable-word", 10)) == ["a-very-long-unbreakable-word"]  # whole


def test_fit_blocks_drops_whole_blocks_and_the_highest_priority_number_first() -> None:
    blocks = [block(3, 0), block(3, 1), block(3, 2)]
    assert len(fit_blocks(blocks, 9)) == 9
    assert len(fit_blocks(blocks, 8)) == 6  # the last block goes whole, nothing is cut to fill the 2 spare rows
    assert shown(fit_blocks(blocks, 3)) == ["row 0", "row 1", "row 2"]
    assert fit_blocks(blocks, 2) == []  # not even the first fits: nothing is better than half of it


def test_equal_priorities_drop_the_later_block_first() -> None:
    first = block(2, 1)
    second = Block((Line(Text("second")), Line(Text("second"))), 1)
    assert shown(fit_blocks([first, second], 2)) == ["row 0", "row 1"]


def test_a_group_that_lost_blocks_ends_in_a_more_line() -> None:
    blocks = [block(2, 1, group="g", more="do:x"), block(2, 2, group="g", more="do:x")]
    lines = fit_blocks(blocks, 3, ">")
    assert shown(lines)[:2] == ["row 0", "row 1"]
    assert lines[-1].text.plain.strip() == "+1 more >" and lines[-1].action == "do:x"


def test_a_heading_goes_when_its_section_has_nothing_left() -> None:
    blocks = [heading("WARNINGS", "ww"), block(2, 1, section="ww"), block(2, 0)]
    assert "WARNINGS" in shown(fit_blocks(blocks, 5))
    assert "WARNINGS" not in shown(fit_blocks(blocks, 2))


# ---- the layout on screen -----------------------------------------------------------------------------------------


def area(widget: Widget) -> int:
    return widget.size.width * widget.size.height


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
async def test_the_map_is_the_largest_widget_at_every_size(size: tuple[int, int]) -> None:
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        screen = app.screen
        assert isinstance(screen, MainScreen)
        map_area = area(screen.query_one(MapView))
        for other in (screen.query_one("#side"), screen.query_one("#strip"), screen.query_one("#lead")):
            if other.display:
                assert map_area > area(other), other.id
        assert map_area > size[0] * size[1] * 0.4


async def test_each_tier_shows_its_own_parts() -> None:
    expected = {
        (80, 24): (Tier.SMALL, False, True),
        (100, 40): (Tier.MEDIUM, True, False),
        (200, 50): (Tier.LARGE, True, False),
    }
    for size, (tier, side, strip) in expected.items():
        app = replay_app()
        async with running(app, size) as pilot:
            await into_the_storm(pilot)
            assert app.screen.has_class(f"tier-{tier.value}")
            assert app.screen.query_one("#side").display is side
            assert app.screen.query_one("#strip").display is strip


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
async def test_no_line_is_wider_than_its_panel_and_no_item_is_clipped(size: tuple[int, int]) -> None:
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        await settle(pilot)
        for panel in app.screen.query(SidePanel):
            if not panel.display or not panel.lines:
                continue
            width = panel.text_width()
            rows = panel.size.height - panel.styles.gutter.height
            assert len(panel.lines) <= rows, (panel.id, len(panel.lines), rows)
            for line in panel.lines:
                assert line.text.cell_len <= width, (panel.id, line.text.plain)
                assert "…" not in line.text.plain, (panel.id, line.text.plain)
        assert "Erin" in screen_text(app)


async def test_a_small_terminal_gets_the_storm_strip_and_a_warnings_line() -> None:
    app = replay_app()
    async with running(app, (80, 24)) as pilot:
        await into_the_storm(pilot)
        plain = [line.text.plain for line in app.screen.query_one("#strip", SidePanel).lines]
        assert plain and "Erin" in plain[0] and "open" in plain[0]
        assert any("Warning" in t or "Watch" in t for t in plain)


def panel_text(app: EyewallApp) -> str:
    """The words in the column beside the map, apart from the map's own columns."""
    return " ".join(" ".join(line.text.plain for line in app.screen.query_one("#side", SidePanel).lines).split())


async def test_the_cards_say_it_in_plain_sentences() -> None:
    app = replay_app()
    async with running(app, (100, 40)) as pilot:
        await into_the_storm(pilot)
        text = panel_text(app)
        assert "Named storms" in text and "Watches and warnings" in text
        assert "Maximum sustained winds are" in text
        assert "Next intermediate advisory" in text or "Next complete advisory" in text
        assert "Tropical Storm Warning" in text and "conditions expected" in text
        assert text.index("Tropical Storm Warning") < text.index("Tropical Storm Watch")  # the most serious first


async def test_the_wide_screen_says_more_on_the_card() -> None:
    app = replay_app()
    async with running(app, (200, 50)) as pilot:
        await into_the_storm(pilot)
        text = panel_text(app)
        assert "Pressure" in text and "Tropical-storm-force winds" in text


# ---- clicks and keys ----------------------------------------------------------------------------------------------


async def test_a_click_on_the_storm_card_opens_the_storm() -> None:
    app = replay_app()
    async with running(app, (100, 40)) as pilot:
        await into_the_storm(pilot)
        panel = app.screen.query_one("#side", SidePanel)
        row = next(i for i, line in enumerate(panel.lines) if (line.action or "").startswith("open:"))
        await pilot.click("#side", offset=(3, row))
        await settle(pilot)
        assert isinstance(app.screen, StormScreen)


async def test_the_small_strip_opens_the_storm_on_click_and_enter_does_too() -> None:
    app = replay_app()
    async with running(app, (80, 24)) as pilot:
        await into_the_storm(pilot)
        await pilot.click("#strip", offset=(3, 0))
        await settle(pilot)
        assert isinstance(app.screen, StormScreen)
        await press(pilot, "escape")
        await press(pilot, "enter")
        assert isinstance(app.screen, StormScreen)


async def test_b_opens_the_buoys_of_the_storm() -> None:
    app = replay_app()
    async with running(app, (100, 40)) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "b")
        assert type(app.screen).__name__ == "BuoysScreen"


async def test_the_full_map_hides_the_panels_and_esc_brings_them_back() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "M")
        assert app.screen.query_one("#side").display is False
        await press(pilot, "escape")
        assert app.screen.query_one("#side").display is True


# ---- nothing active -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
async def test_nothing_active_says_so_and_offers_the_outlook_and_the_replay(size: tuple[int, int]) -> None:
    app = scripted_app()
    async with running(app, size) as pilot:
        await settle(pilot)
        text = " ".join(screen_text(app).split())
        assert "No tropical storms in the Atlantic, East Pacific and Central Pacific right now." in text
        assert "NHC is watching 1 area" in text
        assert "replay" in text.lower()
        assert area(app.screen.query_one(MapView)) > size[0] * size[1] * 0.4
        await press(pilot, "R")  # the live app closes so the recording can have the terminal
        assert app._exit


async def test_nothing_active_lists_the_stations_on_the_wide_screen() -> None:
    app = scripted_app()
    async with running(app, (140, 45)) as pilot:
        await settle(pilot)
        text = " ".join(screen_text(app).split())
        assert "Your stations" in text and "open the list" in text
        await press(pilot, "b")
        assert type(app.screen).__name__ == "BuoysScreen"


async def test_a_replay_has_no_replay_offer() -> None:
    app = replay_app()
    async with running(app, (140, 45)) as pilot:
        await into_the_storm(pilot)
        assert "start the replay" not in screen_text(app)
        await press(pilot, "R")
        assert not app._exit
