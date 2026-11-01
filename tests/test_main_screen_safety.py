"""The main screen never hides a warning: a long list is counted rather than dropped, a storm whose watches and warnings
were not read says so, and a storm feed that has stopped is not reported as "no storms"."""

from __future__ import annotations

from dataclasses import replace

import pytest
from rich.text import Text

from eyewall.app import EyewallApp
from eyewall.models.watches import WatchWarningArea
from eyewall.palette import WatchWarning
from eyewall.state.store import StormState
from eyewall.ui.screens.main import MainScreen, lead_text, side_blocks
from eyewall.ui.screens.nhc_text import NhcTextScreen
from eyewall.ui.widgets import warning_list
from eyewall.ui.widgets.side_panel import Block, Line, SidePanel, fit_blocks, heading
from eyewall.ui.words import Words
from tests.ui_support import (
    ScriptedSource,
    into_the_storm,
    press,
    replay_app,
    running,
    screen_text,
    scripted_app,
    settle,
    wait_until,
)

NOUN = ("watch or warning", "watches and warnings")


def block(rows: int, priority: int = 0, **kwargs: object) -> Block:
    return Block(tuple(Line(Text(f"row {i}")) for i in range(rows)), priority, **kwargs)  # type: ignore[arg-type]


def panel_lines(app: EyewallApp, panel: str = "#side") -> list[str]:
    return [line.text.plain for line in app.screen.query_one(panel, SidePanel).lines]


def panel_text(app: EyewallApp, panel: str = "#side") -> str:
    return " ".join(" ".join(panel_lines(app, panel)).split())


def lead_of(app: EyewallApp) -> str:
    return " ".join(str(app.screen.query_one("#lead").render()).split())


def with_areas(app: EyewallApp, areas: tuple[WatchWarningArea, ...]) -> None:
    """Put these watches and warnings on the storm's current public advisory."""
    state = next(iter(app.store.storms.values()))
    public = state.advisories.public
    assert public is not None
    public = replace(public, watches_warnings=replace(public.watches_warnings, in_effect=areas))
    app.store.storms[state.storm.id] = StormState(state.storm, replace(state.advisories, public=public))


def second_storm(app: EyewallApp) -> str:
    """A copy of the storm under another name, so two storms are in view."""
    state = next(iter(app.store.storms.values()))
    other = replace(state.storm, id="ep092025", name="FERNANDA", intensity_kt=50)
    app.store.storms[other.id] = StormState(other, state.advisories)
    return other.id


def unread(app: EyewallApp, storm_id: str | None = None) -> None:
    state = next(iter(app.store.storms.values())) if storm_id is None else app.store.storms[storm_id]
    app.store.storms[state.storm.id] = StormState(state.storm, replace(state.advisories, public=None))


def area(label: str, kind: WatchWarning, *places: str) -> WatchWarningArea:
    return WatchWarningArea(label, kind, places)


# ---- warnings are never dropped silently --------------------------------------------------------------------------


def test_a_group_that_loses_every_block_still_says_how_many_are_left() -> None:
    """The reviewer's case: a 7-line card, a heading, a 14-line first warning and a 3-line second, in 18 rows."""
    card = block(7, 0)
    head = heading("WATCHES AND WARNINGS", "ww")
    first = block(14, 1, group="ww", section="ww", noun=NOUN, more="open:x")
    second = block(3, 4, group="ww", section="ww", noun=NOUN, more="open:x")
    lines = fit_blocks([card, head, first, second], 18, 40, ">")
    text = [line.text.plain for line in lines]
    assert "WATCHES AND WARNINGS" in text
    assert any("2 watches and warnings >" in t for t in text), text
    assert lines[-1].action == "open:x"  # and it opens them
    assert len(lines) <= 18


def test_a_kept_group_counts_the_blocks_it_lost() -> None:
    lines = fit_blocks([block(2, 0, group="g", more="do:x"), block(2, 3, group="g", more="do:x")], 3, 20, ">")
    assert lines[-1].text.plain.strip() == "+1 more >"


@pytest.mark.parametrize("size", [(100, 40), (200, 50)], ids=lambda s: f"{s[0]}x{s[1]}")
async def test_a_long_list_of_places_is_counted_not_cut_and_the_top_warning_stays(size: tuple[int, int]) -> None:
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        places = tuple(f"Place number {i}, Somewhere County, Carolina" for i in range(40))
        with_areas(
            app,
            (
                area("Tropical Storm Watch", WatchWarning.TROPICAL_STORM_WATCH, "Bermuda"),
                area("Hurricane Warning", WatchWarning.HURRICANE_WARNING, *places),
            ),
        )
        app.screen.refresh_data()
        await settle(pilot)
        text = panel_text(app)
        assert text.index("Hurricane Warning") < text.index("Tropical Storm Watch")  # most serious first
        assert "Place number 0" in text and "more places" in text  # the first place whole, the rest counted
        assert "Place number 39" not in text
        panel = app.screen.query_one("#side", SidePanel)
        assert len(panel.lines) <= panel.size.height


async def test_the_top_warning_outlasts_a_second_storm_card() -> None:
    app = replay_app()
    async with running(app, (100, 30)) as pilot:
        await into_the_storm(pilot)
        second_storm(app)
        app.screen.refresh_data()
        await settle(pilot)
        text = panel_text(app)
        assert "Tropical Storm Warning" in text or "watches and warnings >" in text
        assert "FERNANDA" in text.upper() or "+1 more" in text  # a card that is not shown is counted


async def test_watch_means_possible_and_warning_means_expected() -> None:
    app = replay_app()
    async with running(app, (100, 40)) as pilot:
        await into_the_storm(pilot)
        with_areas(
            app,
            (
                area("Hurricane Watch", WatchWarning.HURRICANE_WATCH, "Bermuda"),
                area("Tropical Storm Warning", WatchWarning.TROPICAL_STORM_WARNING, "Cape Hatteras"),
            ),
        )
        app.screen.refresh_data()
        await settle(pilot)
        text = panel_text(app)
        assert "Hurricane Watch conditions possible" in text
        assert "Tropical Storm Warning conditions expected" in text


async def test_equal_rank_warnings_keep_nhcs_order_and_the_later_goes_first() -> None:
    app = replay_app()
    async with running(app, (100, 40)) as pilot:
        await into_the_storm(pilot)
        names = ("First", "Second", "Third", "Fourth")
        with_areas(
            app, tuple(area("Tropical Storm Warning", WatchWarning.TROPICAL_STORM_WARNING, f"{n} Place") for n in names)
        )
        app.screen.refresh_data()
        view = app.screen._view()  # type: ignore[attr-defined]
        assert [i.area.areas[0] for i in warning_list.items(view)] == [f"{n} Place" for n in names]
        priorities = [b.priority for b in warning_list.blocks(view, 30) if b.group == "ww"]
        assert priorities[0] == 1 and priorities == sorted(
            set(priorities)
        )  # distinct, so the order of dropping is fixed


async def test_the_small_strip_counts_the_rest_of_the_warnings() -> None:
    app = replay_app()
    async with running(app, (80, 24)) as pilot:
        await into_the_storm(pilot)
        plain = panel_lines(app, "#strip")
        assert any("more" in t and "Warning" in t for t in plain), plain


# ---- advisories whose warnings were not read ----------------------------------------------------------------------


@pytest.mark.parametrize("size", [(80, 24), (100, 40)], ids=lambda s: f"{s[0]}x{s[1]}")
async def test_a_storm_whose_warnings_are_not_read_says_so(size: tuple[int, int]) -> None:
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        unread(app)
        app.screen.refresh_data()
        await settle(pilot)
        assert "not yet read" in lead_of(app)
        text = panel_text(app, "#strip" if size[0] < 100 else "#side")
        assert "Erin: watches and warnings not yet read" in text
        assert "No watches or warnings" not in text and "None in effect" not in text


async def test_one_unread_storm_is_not_hidden_by_another_storms_warnings() -> None:
    app = replay_app()
    async with running(app, (100, 40)) as pilot:
        await into_the_storm(pilot)
        other = second_storm(app)
        unread(app, other)
        app.screen.refresh_data()
        await settle(pilot)
        text = panel_text(app)
        assert "Tropical Storm Warning" in text  # Erin's, still shown
        assert "Fernanda: watches and warnings not yet read" in text
        assert "not yet read for Fernanda" in lead_of(app)


# ---- a storm feed that has stopped --------------------------------------------------------------------------------


async def test_a_failed_storm_feed_is_not_reported_as_no_storms(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("eyewall.poll.REFRESH_MIN_GAP", 0.0)
    source = ScriptedSource()
    app = scripted_app(source)
    async with running(app, (140, 45)) as pilot:
        await settle(pilot)
        assert "No tropical storms" in screen_text(app) and app.replay_available()
        source.fail = True
        await press(pilot, "r")
        await wait_until(pilot, lambda: app.poller.freshness("storms").failures > 0, 15)
        await settle(pilot)
        assert "Storm data unavailable (last update" in lead_of(app)
        assert "No tropical storms" not in lead_of(app)
        assert not app.replay_available()  # no offer on the strength of "no storms" that is no longer known
        await press(pilot, "R")
        assert not app._exit


async def test_retained_storms_are_marked_stale_when_the_feed_stops() -> None:
    app = replay_app()
    async with running(app, (100, 40)) as pilot:
        await into_the_storm(pilot)
        assert "stale" not in panel_text(app)
        view = replace(app.screen._view(), storms_old=True, storms_age=900.0)  # type: ignore[attr-defined]
        assert "Storm data is not updating (last update 15m00s ago)" in lead_text(view).plain
        lines = fit_blocks(side_blocks(view, 34), 60, 34)
        assert "stale" in " ".join(line.text.plain for line in lines)


# ---- the outlook ---------------------------------------------------------------------------------------------------


async def test_the_outlook_key_opens_every_area_with_its_exact_chances() -> None:
    app = scripted_app()
    async with running(app, (80, 24)) as pilot:
        await settle(pilot)
        assert panel_lines(app, "#strip")  # never an empty strip
        await press(pilot, "O")
        assert isinstance(app.screen, NhcTextScreen) and app.screen.tab == "outlook"
        body = " ".join(screen_text(app).split())
        assert "7 days:" in body and "40%" in body
        await press(pilot, "escape")
        assert isinstance(app.screen, MainScreen)


async def test_a_long_outlook_is_counted_on_the_strip_and_opens_on_click(monkeypatch: pytest.MonkeyPatch) -> None:
    sentences = [Words("NHC is watching 6 areas.")] + [
        Words(f"Area {i}: a {10 * i}% chance it forms within 2 days and {20 * i}% within 7 days.") for i in range(1, 7)
    ]
    monkeypatch.setattr("eyewall.ui.words.outlook.outlook_sentences", lambda *a: sentences)
    monkeypatch.setattr("eyewall.ui.words.outlook.area_count", lambda *a: 3)
    app = scripted_app()
    async with running(app, (80, 24)) as pilot:
        await settle(pilot)
        plain = panel_lines(app, "#strip")
        assert 0 < len(plain) <= 4 and any("more" in t for t in plain), plain
        await pilot.click("#strip", offset=(3, plain.index(next(t for t in plain if "more" in t))))
        await settle(pilot)
        assert isinstance(app.screen, NhcTextScreen) and app.screen.tab == "outlook"


async def test_the_more_line_on_the_cards_brings_the_next_storm_forward() -> None:
    app = replay_app()
    async with running(app, (100, 30)) as pilot:
        await into_the_storm(pilot)
        second_storm(app)
        app.screen.refresh_data()
        await settle(pilot)
        panel = app.screen.query_one("#side", SidePanel)
        rows = [i for i, line in enumerate(panel.lines) if line.action == "do:cursor(1)"]
        assert rows, panel_lines(app)
        before = app.selected
        await pilot.click("#side", offset=(3, rows[0]))
        await settle(pilot)
        assert app.selected != before
