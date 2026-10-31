"""Pilot tests for the graphics gallery: the detail tab and the screen, over the Erin replay with scripted images.

Nothing here waits on a wall-clock timer: tests wait for state (a picture loaded, a message shown) and set the debounce
to zero. No real terminal graphics were drawn by these tests; the inline path is exercised with a stand-in widget.
"""

from __future__ import annotations

import io
import webbrowser
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from PIL import Image
from textual.widget import Widget

from eyewall.app import EyewallApp
from eyewall.config import Config, GraphicsConfig, MapConfig
from eyewall.models.graphics import FloaterProduct
from eyewall.net import FetchError
from eyewall.render.images import ImageError, InlineBackend, inline_wanted
from eyewall.sources import bundle
from eyewall.sources.replay import ReplaySource
from eyewall.ui import gallery
from eyewall.ui.screens.detail import StormDetailScreen
from eyewall.ui.screens.graphics import GraphicsScreen
from eyewall.ui.widgets import gallery as gallery_widget
from eyewall.ui.widgets.gallery import GalleryPanel, ImageView, _open_frames
from tests.ui_support import EDT, into_the_storm, press, running, settle, wait_until

STILL = "https://cdn.star.nesdis.noaa.gov/FLOATER/data/AL052025/GEOCOLOR/1000x1000.jpg"
LOOP = "https://cdn.star.nesdis.noaa.gov/FLOATER/data/AL052025/GEOCOLOR/AL052025-GEOCOLOR-1000x1000.gif"
AIR = "https://cdn.star.nesdis.noaa.gov/FLOATER/data/AL052025/AirMass/1000x1000.jpg"
STILL_TIME = datetime(2025, 8, 20, 21, 0, tzinfo=UTC)
LOOP_FRAMES = 6


@pytest.fixture(autouse=True)
def _no_debounce(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gallery_widget, "DEBOUNCE_SECONDS", 0)


def picture(size: tuple[int, int] = (60, 40), shade: int = 0) -> bytes:
    img = Image.new("RGB", size, (40 + shade, 90, 160))
    img.paste(Image.new("RGB", (size[0] // 2, size[1] // 2), (250, 250, 250)), (4, 4))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def loop_bytes() -> bytes:
    frames = [Image.new("RGB", (40, 30), (i * 30, 80, 120)) for i in range(LOOP_FRAMES)]
    out = io.BytesIO()
    frames[0].save(out, "GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    return out.getvalue()


class ImageSource(ReplaySource):
    """The Erin replay plus scripted NESDIS imagery and a record of what was fetched."""

    def __init__(self) -> None:
        super().__init__(bundle.resolve_bundle(bundle.DEMO))
        self.fetched: list[str] = []
        self.asked: list[str] = []
        self.failures: dict[str, Exception] = {}
        self.bodies: dict[str, bytes] = {STILL: picture(), LOOP: loop_bytes(), AIR: picture(shade=60)}

    async def satellite(self, storm):
        return (FloaterProduct(storm.id, "GEOCOLOR", "https://n/", STILL, STILL_TIME, None, LOOP),)

    async def satellite_product(self, storm, product):
        self.asked.append(product)
        if product == "AirMass":
            return FloaterProduct(storm.id, product, "https://n/", AIR, STILL_TIME)
        return None

    async def image(self, url):
        self.fetched.append(url)
        if url in self.failures:
            raise self.failures[url]
        if url in self.bodies:
            return self.bodies[url]
        return await super().image(url)


class StandIn(Widget):
    """What `textual_image.widget.Image` is to the gallery: a widget with an `image` attribute."""

    def __init__(self, image=None, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.image = image


def app_for(source: ImageSource | None = None, config: Config | None = None, **kw: object) -> EyewallApp:
    return EyewallApp(config or Config(), source or ImageSource(), autoplay=False, local_tz=EDT, **kw)  # type: ignore[arg-type]


def view_text(panel: GalleryPanel) -> str:
    return "\n".join(strip.text for strip in panel.query_one(ImageView)._lines)


def caption(panel: GalleryPanel) -> str:
    return str(panel.query_one("#gal-caption").render())


def current_titles(panel: GalleryPanel) -> list[str]:
    return [i.title for i in panel.items]


def messages(app: EyewallApp) -> list[str]:
    return [n.message for n in app._notifications]


async def open_gallery(pilot, steps: int = 14) -> GalleryPanel:  # type: ignore[no-untyped-def]
    await into_the_storm(pilot, steps)
    await press(pilot, "g")
    assert isinstance(pilot.app.screen, GraphicsScreen)
    return pilot.app.screen.query_one(GalleryPanel)


async def loaded(pilot, panel: GalleryPanel, title: str | None = None) -> None:  # type: ignore[no-untyped-def]
    await wait_until(
        pilot,
        lambda: panel._frames is not None and (title is None or (panel.current and panel.current.title == title)),
        15,
    )


async def pick(pilot, panel: GalleryPanel, title: str) -> None:  # type: ignore[no-untyped-def]
    index = current_titles(panel).index(title)
    panel.query_one("#gal-list").highlighted = index
    await settle(pilot)


# ---- the detail tab -----------------------------------------------------------------------------------------------


async def test_the_graphics_tab_lists_the_images_and_draws_the_cone_with_its_address() -> None:
    source = ImageSource()
    app = app_for(source)
    async with running(app) as pilot:
        await into_the_storm(pilot)
        assert source.fetched == []  # nothing is fetched before anyone looks
        await press(pilot, "enter", "9")
        assert isinstance(app.screen, StormDetailScreen)
        panel = app.screen.query_one(GalleryPanel)
        await loaded(pilot, panel, "Cone, 5 day")
        titles = current_titles(panel)
        assert titles[0] == "Cone, 5 day"
        assert "GEOCOLOR still" in titles and "GEOCOLOR loop" in titles
        assert "replay:graphics/cone_038.png" in caption(panel)
        assert view_text(panel).strip()  # the fallback drew cells
        assert source.fetched == ["replay:graphics/cone_038.png"]


async def test_leaving_the_tab_stops_everything_and_fetches_nothing_new() -> None:
    source = ImageSource()
    app = app_for(source)
    async with running(app) as pilot:
        await into_the_storm(pilot)
        await press(pilot, "enter", "9")
        panel = app.screen.query_one(GalleryPanel)
        await loaded(pilot, panel)
        await pick(pilot, panel, "GEOCOLOR loop")
        await loaded(pilot, panel, "GEOCOLOR loop")
        assert panel._timer is not None  # the loop is playing
        await press(pilot, "1")
        assert not panel.active and panel._timer is None
        seen = list(source.fetched)
        await into_the_storm(pilot, 1)  # a new advisory arrives while the tab is hidden
        assert source.fetched == seen
        await press(pilot, "9")
        assert panel.active


async def test_a_picture_is_fetched_once_and_again_only_when_the_advisory_changes() -> None:
    source = ImageSource()
    app = app_for(source)
    async with running(app) as pilot:
        await into_the_storm(pilot, 13)
        await press(pilot, "g")
        panel = app.screen.query_one(GalleryPanel)
        await loaded(pilot, panel, "Cone, 5 day")
        assert source.fetched == ["replay:graphics/cone_033.png"]
        await pick(pilot, panel, "GEOCOLOR still")
        await loaded(pilot, panel, "GEOCOLOR still")
        await pick(pilot, panel, "Cone, 5 day")
        await wait_until(pilot, lambda: panel._shown is not None and panel._shown[0].startswith("cone"))
        assert source.fetched.count("replay:graphics/cone_033.png") == 1  # kept in memory, not asked for again
        await into_the_storm(pilot, 1)  # advisory 38: a new cone
        await wait_until(pilot, lambda: "replay:graphics/cone_038.png" in source.fetched, 15)
        assert source.fetched.count("replay:graphics/cone_038.png") == 1


async def test_the_other_satellite_products_are_asked_for_once_when_the_gallery_opens() -> None:
    source = ImageSource()
    app = app_for(source)
    async with running(app) as pilot:
        panel = await open_gallery(pilot)
        await wait_until(pilot, lambda: "Air mass still" in current_titles(panel), 15)
        await wait_until(pilot, lambda: {"AirMass", "13"} <= set(source.asked), 15)
        asked = sorted(source.asked)
        assert len(set(asked)) == len(asked)  # one question per product
        await press(pilot, "escape", "g")
        await settle(pilot)
        assert sorted(source.asked) == asked  # remembered for ten minutes: reopening asks nothing


# ---- loops --------------------------------------------------------------------------------------------------------


async def test_a_loop_steps_with_the_bracket_keys_pauses_and_plays() -> None:
    app = app_for()
    async with running(app) as pilot:
        panel = await open_gallery(pilot)
        await pick(pilot, panel, "GEOCOLOR loop")
        await loaded(pilot, panel, "GEOCOLOR loop")
        assert panel._frames is not None and panel._frames.count == LOOP_FRAMES
        assert panel._cursor is not None and panel._cursor.playing and panel._timer is not None
        await press(pilot, "right_square_bracket")  # steps and pauses
        assert not panel._cursor.playing and panel._timer is None
        frozen = panel._cursor.index
        await press(pilot, "left_square_bracket", "left_square_bracket")
        assert panel._cursor.index == (frozen - 2) % LOOP_FRAMES
        assert "paused" in caption(panel) and f"/{LOOP_FRAMES}" in caption(panel)
        await press(pilot, "space")
        assert panel._cursor.playing and panel._timer is not None
        await press(pilot, "space")
        assert not panel._cursor.playing and panel._timer is None


async def test_the_bracket_keys_on_a_still_go_on_to_the_replay_transport() -> None:
    app = app_for()
    async with running(app) as pilot:
        panel = await open_gallery(pilot, 13)
        await loaded(pilot, panel, "Cone, 5 day")
        before = app.replay.now()
        await press(pilot, "right_square_bracket")  # a still has no frames: this is the next advisory
        assert app.replay.now() > before


async def test_a_loop_that_fails_while_playing_stops_with_a_toast_and_the_app_lives(monkeypatch) -> None:
    app = app_for()
    async with running(app) as pilot:
        panel = await open_gallery(pilot)
        await pick(pilot, panel, "GEOCOLOR loop")
        await loaded(pilot, panel, "GEOCOLOR loop")

        def boom() -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(panel, "_paint", boom)
        panel._tick()
        await settle(pilot)
        assert panel._timer is None
        assert any("loop stopped" in m for m in messages(app))
        await press(pilot, "escape")
        assert not isinstance(app.screen, GraphicsScreen)


# ---- failures stay in the picture area ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("failure", "words"),
    [
        (FetchError(STILL, "HTTP 503"), "HTTP 503"),
        (RuntimeError("decoder blew up"), "decoder blew up"),
    ],
    ids=["network", "unexpected"],
)
async def test_a_failing_image_becomes_a_message_not_a_crash(failure: Exception, words: str) -> None:
    source = ImageSource()
    source.failures[STILL] = failure
    app = app_for(source)
    async with running(app) as pilot:
        panel = await open_gallery(pilot)
        await pick(pilot, panel, "GEOCOLOR still")
        await wait_until(pilot, lambda: words in view_text(panel), 15)
        await press(pilot, "down")  # the list still works
        assert app.is_running


async def test_a_page_in_place_of_a_picture_is_said_in_words() -> None:
    source = ImageSource()
    source.bodies[STILL] = b"<html>maintenance</html>"
    app = app_for(source)
    async with running(app) as pilot:
        panel = await open_gallery(pilot)
        await pick(pilot, panel, "GEOCOLOR still")
        await wait_until(pilot, lambda: "not a readable image" in view_text(panel), 15)
        assert panel._frames is None


async def test_a_storm_with_no_graphics_yet_says_so() -> None:
    app = app_for()
    async with running(app) as pilot:
        # The replay opens on its first advisory, which has no graphics; satellite imagery is the only content.
        await press(pilot, "g")
        panel = app.screen.query_one(GalleryPanel)
        assert "Cone, 5 day" not in current_titles(panel)


# ---- open and copy ------------------------------------------------------------------------------------------------


async def test_y_copies_the_address_and_o_opens_it(monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", lambda url, *a, **k: opened.append(url) or True)
    app = app_for()
    async with running(app) as pilot:
        panel = await open_gallery(pilot)
        await pick(pilot, panel, "GEOCOLOR still")
        await loaded(pilot, panel, "GEOCOLOR still")
        await press(pilot, "y")
        assert app.clipboard == STILL
        await press(pilot, "o")
        assert opened == [STILL]


async def test_o_and_y_degrade_when_there_is_no_browser_or_clipboard(monkeypatch) -> None:
    def no_browser(url: str, *args: object, **kwargs: object) -> bool:
        raise webbrowser.Error("no runnable browser")

    def no_clipboard(text: str) -> None:
        raise OSError("no clipboard")

    monkeypatch.setattr(webbrowser, "open", no_browser)
    app = app_for()
    async with running(app) as pilot:
        panel = await open_gallery(pilot)
        await pick(pilot, panel, "GEOCOLOR still")
        monkeypatch.setattr(app, "copy_to_clipboard", no_clipboard)
        await press(pilot, "o", "y")
        assert sum(STILL in m for m in messages(app)) == 2  # both say the address instead of failing
        assert app.is_running
        monkeypatch.setattr(webbrowser, "open", lambda url, *a, **k: False)
        await press(pilot, "o")
        assert "No browser" in messages(app)[-1]


async def test_a_recorded_still_has_no_web_address_to_open(monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", lambda url, *a, **k: opened.append(url) or True)
    app = app_for()
    async with running(app) as pilot:
        panel = await open_gallery(pilot)
        await loaded(pilot, panel, "Cone, 5 day")
        await press(pilot, "o")
        assert opened == []
        assert any("recording" in m for m in messages(app))
        await press(pilot, "y")
        assert app.clipboard == "replay:graphics/cone_038.png"


# ---- inline or fallback -------------------------------------------------------------------------------------------


async def test_an_inline_backend_draws_the_picture_with_the_cone_cropped() -> None:
    app = app_for(inline=InlineBackend("sixel", StandIn))
    async with running(app) as pilot:
        panel = await open_gallery(pilot)
        await loaded(pilot, panel, "Cone, 5 day")
        widget = panel.query_one("#gal-inline", StandIn)
        assert widget.display and isinstance(widget.image, Image.Image)
        assert widget.image.size[1] < 736 * 0.78  # the legend block was cropped off
        assert not panel.query_one(ImageView).display


@pytest.mark.parametrize(
    "config",
    [Config(graphics=GraphicsConfig("never")), Config(map=MapConfig(glyph_set="ascii"))],
    ids=["inline-never", "glyphs-ascii"],
)
async def test_inline_is_not_used_when_the_config_or_glyph_set_says_no(config: Config) -> None:
    app = app_for(config=config, inline=InlineBackend("sixel", StandIn))
    async with running(app) as pilot:
        panel = await open_gallery(pilot)
        await loaded(pilot, panel, "Cone, 5 day")
        assert not panel.query("#gal-inline")
        assert view_text(panel).strip()


async def test_the_ascii_glyph_set_draws_with_ascii_characters_only() -> None:
    app = app_for(config=Config(map=MapConfig(glyph_set="ascii")))
    async with running(app) as pilot:
        panel = await open_gallery(pilot)
        await loaded(pilot, panel, "Cone, 5 day")
        assert set(view_text(panel)) <= set(" .:-=+*#%@\n")


@pytest.mark.parametrize("size", [(80, 24), (140, 45)], ids=["80x24", "140x45"])
async def test_the_gallery_fits_small_and_large_terminals(size: tuple[int, int]) -> None:
    app = app_for()
    async with running(app, size) as pilot:
        panel = await open_gallery(pilot)
        await loaded(pilot, panel, "Cone, 5 day")
        view = panel.query_one(ImageView)
        assert 0 < len(view._lines) <= view.size.height
        assert all(line.cell_length <= view.size.width for line in view._lines)


def test_the_satellite_products_are_the_ones_the_brief_names() -> None:
    assert [label for _, label in gallery.SATELLITE_PRODUCTS] == ["GEOCOLOR", "Air mass", "Infrared"]


# ---- what the app remembers ---------------------------------------------------------------------------------------


async def test_the_app_keeps_images_by_address_and_version_within_a_memory_budget(monkeypatch) -> None:
    import eyewall.app as app_module

    source = ImageSource()
    app = app_for(source)
    url = "replay:graphics/cone_033.png"
    first = await app.load_image(url, "33")
    assert await app.load_image(url, "33") is first and source.fetched == [url]
    await app.load_image(url, "34")  # a new version of the same address replaces the old copy
    assert source.fetched == [url, url] and list(app._images) == [(url, "34")]
    monkeypatch.setattr(app_module, "IMAGE_MEMORY", len(first) + 10)
    await app.load_image("replay:graphics/cone_038.png", "38")
    assert list(app._images) == [("replay:graphics/cone_038.png", "38")]  # the oldest went to make room


async def test_a_satellite_listing_is_remembered_and_a_failed_one_keeps_the_last_good_answer() -> None:
    source = ImageSource()
    app = app_for(source)
    async with running(app) as pilot:
        await into_the_storm(pilot)
        storm_id = next(iter(app.store.storms))
        assert await app.floater(storm_id, "AirMass") is True
        assert await app.floater(storm_id, "AirMass") is False and source.asked.count("AirMass") == 1
        assert app.floaters_for(storm_id)["AirMass"].still_url == AIR
        app._floaters[(storm_id, "AirMass")] = (0.0, app._floaters[(storm_id, "AirMass")][1])  # long ago

        async def down(storm, product):
            raise FetchError("x", "down")

        source.satellite_product = down  # type: ignore[method-assign]
        assert await app.floater(storm_id, "AirMass") is False
        assert app.floaters_for(storm_id)["AirMass"] is not None
        assert await app.floater("al000000", "AirMass") is False  # a storm that is gone


def test_the_terminal_is_probed_only_when_inline_graphics_are_possible(monkeypatch) -> None:
    import eyewall.app as app_module

    asked: list[str] = []
    monkeypatch.setattr(app_module, "load_inline", lambda mode: asked.append(mode))
    monkeypatch.setattr(EyewallApp, "run", lambda self, *a, **k: None)
    for config in (Config(), Config(graphics=GraphicsConfig("never")), Config(map=MapConfig(glyph_set="ascii"))):
        app_module.run_app(config, replay_source_for_run(), state_dir=None)
    assert asked == ["auto"]  # neither "never" nor the ascii glyph set probes the terminal


def replay_source_for_run() -> ReplaySource:
    return ReplaySource(bundle.resolve_bundle(bundle.DEMO))


# ---- review fixes -------------------------------------------------------------------------------------------------


async def test_a_gallery_under_another_screen_is_inactive_and_wakes_with_its_tab() -> None:
    app = app_for()
    async with running(app) as pilot:
        await into_the_storm(pilot, 14)
        await press(pilot, "enter", "9")
        detail = app.screen
        assert isinstance(detail, StormDetailScreen)
        panel = detail.query_one(GalleryPanel)
        assert panel.active
        await press(pilot, "question_mark")
        assert not panel.active
        await press(pilot, "escape")
        assert panel.active
        await press(pilot, "1")
        assert not panel.active
        await press(pilot, "question_mark", "escape")
        assert not panel.active  # coming back to another tab does not wake it


async def test_a_failed_image_is_not_fetched_again_by_a_refresh_only_by_a_new_version_or_a_new_pick() -> None:
    source = ImageSource()
    source.failures[STILL] = FetchError(STILL, "HTTP 503")
    app = app_for(source)
    async with running(app) as pilot:
        panel = await open_gallery(pilot)
        await pick(pilot, panel, "GEOCOLOR still")
        await wait_until(pilot, lambda: "HTTP 503" in view_text(panel), 15)
        before = source.fetched.count(STILL)
        for _ in range(3):
            panel.refresh_data()
            await settle(pilot)
        assert source.fetched.count(STILL) == before
        await pick(pilot, panel, "GEOCOLOR loop")
        await loaded(pilot, panel, "GEOCOLOR loop")
        del source.failures[STILL]
        await pick(pilot, panel, "GEOCOLOR still")
        await loaded(pilot, panel, "GEOCOLOR still")
        assert source.fetched.count(STILL) == before + 1


def test_a_picture_with_no_version_is_stamped_with_the_poll_that_listed_it() -> None:
    from tests.state_support import make_storm

    storm = make_storm("1", storm_id="al052025")
    product = FloaterProduct(storm.id, "GEOCOLOR", "https://n/", STILL, None, None, LOOP)
    state = gallery.StormState(storm, satellite=(product,), fetched_key=("5", None))
    first = {i.key: i.version for i in gallery.build_items(state)}
    second = {i.key: i.version for i in gallery.build_items(replace(state, fetched_key=("6", None)))}
    assert first["sat:GEOCOLOR:still"] != second["sat:GEOCOLOR:still"]
    assert first["sat:GEOCOLOR:still"] not in ("", "latest")


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        (STILL, True),
        ("https://www.nhc.noaa.gov/storm_graphics/AL05/x.png", True),
        ("https://forecast.weather.gov/x", True),
        ("https://noaa.gov.evil.test/x", False),
        ("https://evilnoaa.gov/x", False),
        ("https://example.test/x?u=https://noaa.gov/", False),
        ("file:///c:/noaa.gov/x", False),
    ],
)
def test_only_noaa_hosts_are_opened(url: str, ok: bool) -> None:
    assert gallery_widget.is_noaa_url(url) is ok


async def test_o_refuses_a_link_that_is_not_noaa_and_notices_do_not_read_the_address_as_markup(monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", lambda url, *a, **k: opened.append(url) or True)
    app = app_for()
    async with running(app) as pilot:
        panel = await open_gallery(pilot)
        await loaded(pilot, panel, "Cone, 5 day")
        panel.current = gallery.GalleryItem("x", "forecast", "Odd", "https://example.test/[bold]x.png", "png", "1")
        await press(pilot, "o")
        assert opened == [] and "Not a NOAA link." in messages(app)
        monkeypatch.setattr(app, "copy_to_clipboard", lambda text: (_ for _ in ()).throw(OSError("no")))
        await press(pilot, "y")
        note = next(n for n in app._notifications if "clipboard" in n.message)
        assert note.markup is False


def test_one_predicate_decides_whether_inline_graphics_are_possible() -> None:
    assert inline_wanted("auto", "unicode")
    assert not inline_wanted("never", "unicode")
    assert not inline_wanted("auto", "ascii")


def test_the_first_frame_is_decoded_when_the_image_is_opened_not_when_it_is_drawn() -> None:
    out = io.BytesIO()
    first = Image.new("RGB", (8, 8), (255, 0, 0))
    first.save(out, "GIF", save_all=True, append_images=[Image.new("RGB", (8, 8), (0, 0, 255))], duration=100)
    frames = _open_frames(out.getvalue())
    assert list(frames._cache) == [0] and frames.animated
    with pytest.raises(ImageError):
        _open_frames(b"not an image")
