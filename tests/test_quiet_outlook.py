"""A quiet Home says what NHC expects, basin by basin, and never says "nothing expected" on the strength of a feed that
failed. Text-level: the words, the panel and the keys, no snapshots."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from eyewall.models.outlook import Outlook, OutlookGis, OutlookSystem
from eyewall.net import FetchError
from eyewall.providers.base import ParseError
from eyewall.providers.nhc.client import NhcClient
from eyewall.providers.nhc.ids import Basin
from eyewall.providers.nhc.text import parse_two
from eyewall.ui.chrome import footer_items
from eyewall.ui.words.outlook import current_sentences, outlook_sentences
from eyewall.ui.words.summary import summary_lines
from tests.test_main_screen import panel_text
from tests.ui_support import (
    FIXTURES,
    ScriptedSource,
    press,
    quiet_outlook,
    running,
    screen_text,
    scripted_app,
    settle,
    wait_until,
)

ALL = ("AL", "EP", "CP")
NOT_EXPECTED = "Tropical cyclone formation is not expected during the next 7 days."

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


def two(*names: str) -> tuple:  # type: ignore[type-arg]
    return tuple(parse_two((FIXTURES / "nhc" / "two" / f"{n}.txt").read_text(encoding="utf-8")) for n in names)


def lines(outlook: Outlook, enabled: tuple[str, ...] = ALL) -> list[str]:
    return [w.text for w in outlook_sentences(outlook, enabled, NOW)]


def square(lat: float, lon: float, half: float = 1.0) -> tuple[tuple[float, float], ...]:
    return ((lat - half, lon - half), (lat - half, lon + half), (lat + half, lon + half), (lat + half, lon - half))


def nothing_anywhere() -> Outlook:
    return Outlook(texts=two("at_20261031"))


def test_each_basin_without_an_area_says_so_in_nhcs_words() -> None:
    texts = tuple(replace(t, areas=(), summary=NOT_EXPECTED) for t in two("at_20261031", "ep_20261031", "cp_20261031"))
    said = lines(Outlook(texts=texts))
    assert said == [
        f"Atlantic: {NOT_EXPECTED}",
        f"East Pacific: {NOT_EXPECTED}",
        f"Central Pacific: {NOT_EXPECTED}",
    ]  # one text speaks for both Pacific basins and another for the Central one: each is said once


def test_one_enabled_basin_keeps_the_summary_as_issued() -> None:
    assert lines(nothing_anywhere(), ("AL",)) == [NOT_EXPECTED]


def test_an_area_in_one_basin_does_not_hide_the_quiet_of_the_others() -> None:
    said = lines(quiet_outlook())
    assert said[0].startswith("NHC is watching 1 area in the Central Pacific: a 40% chance")
    assert f"Atlantic: {NOT_EXPECTED}" in said
    assert not any(s.startswith("Central Pacific:") for s in said)


def pacific_quiet(*systems: OutlookSystem) -> Outlook:
    """The combined East/Central Pacific text with no area, the Atlantic text, and shapes for `systems`."""
    texts = tuple(replace(t, areas=(), summary=NOT_EXPECTED) for t in two("at_20261031", "ep_20261031"))
    return Outlook(texts=texts, gis=OutlookGis(None, systems))


def test_a_central_pacific_area_leaves_the_east_pacific_quiet_said() -> None:
    said = lines(pacific_quiet(OutlookSystem("Pacific", "1", 0, "low", 40, "medium", polygons=(square(12.0, -150.0),))))
    assert said[0].startswith("NHC is watching 1 area in the Central Pacific")
    assert f"East Pacific: {NOT_EXPECTED}" in said and f"Atlantic: {NOT_EXPECTED}" in said
    assert not any(s.startswith("Central Pacific:") for s in said)


def test_an_east_pacific_area_leaves_the_central_pacific_quiet_said() -> None:
    said = lines(pacific_quiet(OutlookSystem("Pacific", "1", 0, "low", 40, "medium", polygons=(square(12.0, -120.0),))))
    assert said[0].startswith("NHC is watching 1 area in the East Pacific")
    assert f"Central Pacific: {NOT_EXPECTED}" in said
    assert not any(s.startswith("East Pacific:") for s in said)


def test_a_basin_that_is_off_is_not_reported() -> None:
    said = lines(quiet_outlook(), ("AL",))
    assert said == [NOT_EXPECTED]  # the Pacific area is out of this view, and so is its quiet


def test_nothing_is_said_for_an_outlook_that_never_arrived() -> None:
    assert lines(Outlook(gis=OutlookGis(None))) == ["No outlook has been issued yet."]
    assert [w.text for w in outlook_sentences(None, ALL, NOW)] == ["Waiting for the first outlook."]


async def test_a_blank_200_is_a_failure_not_an_empty_outlook(monkeypatch: pytest.MonkeyPatch) -> None:
    client = object.__new__(NhcClient)
    for body in ("", "  \n"):

        async def fetch(basin: Basin, *, fallback: bool = False, _body: str = body):  # type: ignore[no-untyped-def]
            return type("R", (), {"value": _body})()

        monkeypatch.setattr(client, "fetch_outlook_text", fetch, raising=False)
        with pytest.raises(ParseError):
            await client.outlook_basin(Basin.AL)


async def test_garbage_in_a_200_is_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    client = object.__new__(NhcClient)

    async def fetch(basin: Basin, *, fallback: bool = False):  # type: ignore[no-untyped-def]
        return type("R", (), {"value": "<html>Service unavailable</html>"})()

    monkeypatch.setattr(client, "fetch_outlook_text", fetch, raising=False)
    with pytest.raises(ParseError):
        await client.outlook_basin(Basin.AL)


@pytest.mark.parametrize("size", [(60, 16), (80, 24), (120, 40)], ids=lambda s: f"{s[0]}x{s[1]}")
async def test_the_quiet_screen_names_the_areas_at_every_size(size: tuple[int, int]) -> None:
    app = scripted_app()
    async with running(app, size) as pilot:
        await settle(pilot)
        assert type(app.screen).__name__ == "MainScreen"
        text = " ".join(screen_text(app).split()) + " " + panel_text(app)
        assert "Central Pacific" in text or "1 area" in text  # truncated to fit, never empty
        for row in screen_text(app).splitlines():
            assert len(row) <= size[0]
        if size[0] >= 100:
            assert f"Atlantic: {NOT_EXPECTED}" in panel_text(app)


async def test_a_terminal_under_the_minimum_keeps_the_too_small_notice() -> None:
    app = scripted_app()
    async with running(app, (59, 16)) as pilot:
        await settle(pilot)
        assert type(app.screen).__name__ == "TooSmallScreen"
        await press(pilot, "enter")
        assert type(app.screen).__name__ == "TooSmallScreen"


async def test_a_stale_outlook_says_so_and_does_not_claim_nothing_is_expected() -> None:
    app = scripted_app(ScriptedSource(nothing_anywhere()))
    async with running(app, (120, 40)) as pilot:
        await settle(pilot)
        assert NOT_EXPECTED in panel_text(app)
        from eyewall.ui.widgets.side_info import outlook_text

        view = replace(app.screen._view(), outlook_old=True)  # type: ignore[attr-defined]
        said = " ".join(outlook_text(view))
        assert "may be out of date" in said and "not expected" not in said


async def test_a_stale_outlook_still_names_its_areas() -> None:
    app = scripted_app()
    async with running(app, (120, 40)) as pilot:
        await settle(pilot)
        from eyewall.ui.widgets.side_info import outlook_text

        view = replace(app.screen._view(), outlook_old=True)  # type: ignore[attr-defined]
        said = outlook_text(view)
        assert "may be out of date" in said[0] and "1 area in the Central Pacific" in said[1]
        assert len(said) == 2


async def test_enter_on_a_quiet_home_opens_the_outlook_when_an_area_is_watched() -> None:
    app = scripted_app()
    async with running(app, (120, 40)) as pilot:
        await settle(pilot)
        assert "open" in [i.label for i in footer_items(app.screen)[0]]
        await press(pilot, "enter")
        await settle(pilot)
        assert type(app.screen).__name__ == "NhcTextScreen"


async def test_enter_is_not_offered_on_a_quiet_home_with_nothing_to_open() -> None:
    app = scripted_app(ScriptedSource(nothing_anywhere()))
    async with running(app, (120, 40)) as pilot:
        await settle(pilot)
        assert "open" not in [i.label for i in footer_items(app.screen)[0]]
        await press(pilot, "enter")
        await settle(pilot)
        assert type(app.screen).__name__ == "MainScreen"


def test_the_plain_summary_does_not_say_not_expected_when_the_outlook_feed_failed() -> None:
    old = current_sentences(nothing_anywhere(), ("AL",), NOW, old=True)
    assert len(old) == 1 and "may be out of date" in old[0]
    assert current_sentences(nothing_anywhere(), ("AL",), NOW, old=False) == [NOT_EXPECTED]


async def test_the_summary_text_follows_the_failed_feed() -> None:
    app = scripted_app(ScriptedSource(nothing_anywhere()))
    async with running(app, (120, 40)) as pilot:
        await settle(pilot)
        args = (app.store, app.preset, app.now())
        assert NOT_EXPECTED in " ".join(summary_lines(*args))
        said = " ".join(summary_lines(*args, failed=frozenset({"outlook"})))
        assert "may be out of date" in said and "not expected" not in said


async def test_a_storm_view_does_not_gain_the_quiet_basins() -> None:
    from eyewall.ui.widgets.side_info import outlook_text
    from tests.ui_support import into_the_storm, replay_app

    app = replay_app()
    async with running(app, (120, 40)) as pilot:
        await into_the_storm(pilot)
        app.store.outlook = quiet_outlook()
        view = app.screen._view()  # type: ignore[attr-defined]
        said = outlook_text(view)
        assert said and not any("not expected" in s for s in said)


class OutlookFlaky(ScriptedSource):
    """Serves its outlook until `fail_outlook` is set, then fails that feed alone."""

    fail_outlook = False

    async def outlook(self) -> Outlook:
        if self.fail_outlook:
            raise FetchError("scripted://outlook", "outage")
        return await super().outlook()


async def test_a_real_outlook_failure_marks_the_panel_out_of_date(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("eyewall.poll.REFRESH_MIN_GAP", 0.0)
    source = OutlookFlaky(nothing_anywhere())
    app = scripted_app(source)
    async with running(app, (120, 40)) as pilot:
        await settle(pilot)
        assert NOT_EXPECTED in panel_text(app) and "out of date" not in panel_text(app)
        source.fail_outlook = True
        await press(pilot, "r")
        await wait_until(pilot, lambda: app.poller.freshness("outlook").failures > 0, 15)
        await settle(pilot)
        assert "may be out of date" in panel_text(app)
        assert "not expected" not in panel_text(app)


async def test_enter_appears_in_the_footer_when_the_first_area_arrives(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("eyewall.poll.REFRESH_MIN_GAP", 0.0)
    source = ScriptedSource(nothing_anywhere())
    app = scripted_app(source)
    async with running(app, (120, 40)) as pilot:
        await settle(pilot)
        assert "open" not in [i.label for i in footer_items(app.screen)[0]]
        source._outlook = quiet_outlook()
        await press(pilot, "r")
        await wait_until(pilot, lambda: "open" in [i.label for i in footer_items(app.screen)[0]], 15)
        assert "open" in screen_text(app).splitlines()[-1]
        source._outlook = nothing_anywhere()
        await press(pilot, "r")
        await wait_until(pilot, lambda: "open" not in [i.label for i in footer_items(app.screen)[0]], 15)
        assert "open" not in screen_text(app).splitlines()[-1]
