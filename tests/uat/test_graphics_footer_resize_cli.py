"""Graphics, the focus footer, every screen at the large sizes, resizing across thresholds, too small, and the CLI."""

from __future__ import annotations

import re
import subprocess
import sys

import pytest

from eyewall.app import EyewallApp
from eyewall.config import Config, GraphicsConfig
from eyewall.net import FetchError
from eyewall.ui.screens.dashboard import DashboardScreen
from eyewall.ui.screens.graphics import GraphicsScreen
from eyewall.ui.screens.small import TooSmallScreen
from eyewall.ui.widgets.gallery import GalleryPanel, ImageView
from tests.test_ui_graphics import STILL, ImageSource
from tests.uat.harness import EXTRA_SIZES, SIZES
from tests.ui_support import EDT, replay_app, scripted_app


def gallery_app(config: Config | None = None) -> EyewallApp:
    return EyewallApp(config or Config(), ImageSource(), autoplay=False, local_tz=EDT)


async def gallery_ready(j, title: str | None = None) -> GalleryPanel:
    panel = j.screen.query_one(GalleryPanel)
    for _ in range(200):
        if panel._frames is not None and (title is None or (panel.current and panel.current.title == title)):
            break
        await j.pilot.pause(0.05)
    else:
        raise AssertionError(f"the gallery never showed {title!r}\n{j.text()}")
    await j.settle()
    return panel


def current_frame(j) -> int:  # type: ignore[no-untyped-def]
    found = re.search(r"frame (\d+)/6", j.text())
    assert found, j.text()
    return int(found.group(1))


async def pick(j, panel: GalleryPanel, title: str) -> None:
    panel.query_one("#gal-list").highlighted = [i.title for i in panel.items].index(title)
    await gallery_ready(j, title)


@pytest.fixture(autouse=True)
def _no_debounce(monkeypatch: pytest.MonkeyPatch) -> None:
    from eyewall.ui.widgets import gallery

    monkeypatch.setattr(gallery, "DEBOUNCE_SECONDS", 0)


async def test_graphics_gallery_stills_and_animation(journey, size) -> None:
    async with journey(size, app=gallery_app()) as j:
        await j.keys("g")
        assert isinstance(j.screen, GraphicsScreen)
        panel = await gallery_ready(j, "Cone, 5 day")
        j.see("Cone, 5 day", "replay:graphics/cone_038.png")
        await j.shot("cone")
        await pick(j, panel, "GEOCOLOR still")
        j.see(STILL.rsplit("/", 1)[0].split("//")[1][:10])
        await j.shot("still")
        await pick(j, panel, "GEOCOLOR loop")
        await j.keys("space")  # pause the loop so the frame counter stands still
        assert panel._timer is None
        frame = current_frame(j)
        await j.keys("right_square_bracket")
        assert current_frame(j) == frame % 6 + 1
        await j.shot("loop-stepped")
        await j.keys("left_square_bracket", "left_square_bracket")
        assert current_frame(j) == (frame - 2) % 6 + 1  # one step back past the start wraps to the last frame
        await j.shot("loop-stepped-back")
        await j.keys("space")
        j.see("playing")
        await j.keys("space")
        j.see("paused")
        await j.keys("escape")
        assert not isinstance(j.screen, GraphicsScreen)


async def test_graphics_tab_and_open_key(journey, size) -> None:
    async with journey(size, app=gallery_app()) as j:
        await j.keys("enter", "9")
        panel = await gallery_ready(j, "Cone, 5 day")
        await j.shot("graphics-tab")
        await j.keys("o")
        assert "part of the recording" in j.toasts()
        assert panel.active


async def test_inline_graphics_off_uses_the_cell_fallback(journey, size) -> None:
    config = Config(graphics=GraphicsConfig(inline="off"))
    async with journey(size, app=gallery_app(config)) as j:
        await j.keys("g")
        panel = await gallery_ready(j, "Cone, 5 day")
        assert not panel.uses_inline
        assert "".join(s.text for s in panel.query_one(ImageView)._lines).strip()
        await j.shot("inline-off")


async def test_a_failed_image_says_so(journey, size) -> None:
    source = ImageSource()
    source.failures["replay:graphics/cone_038.png"] = FetchError("replay:graphics/cone_038.png", "scripted failure")
    app = EyewallApp(Config(), source, autoplay=False, local_tz=EDT)
    async with journey(size, app=app) as j:
        await j.keys("g")
        for _ in range(100):
            if "Could not" in j.text():
                break
            await j.pilot.pause(0.05)
        j.see("Could not")
        await j.shot("image-failed")


async def test_footer_follows_the_focus(journey, size) -> None:
    wide = size[0] >= 110
    async with journey(size) as j:
        j.footer_has("enter detail")
        await j.shot("list-focused")
        if wide:
            await j.keys("tab")
            j.footer_has("zoom", "fit", "center", "layers")
            await j.shot("map-focused")
        await j.keys("enter", "3")
        j.footer_has("t tcp/tcm" if wide else "t")
        await j.shot("detail-advisory")
        await j.keys("7")
        j.footer_has("enter charts")
        await j.keys("8")
        j.footer_has("p pin")
        await j.keys("9")
        await j.shot("detail-graphics")
        await j.keys("1")
        j.footer_has("esc back")
        await j.shot("detail-summary")
        await j.keys("escape", "b", "enter")
        j.footer_has("h range" if wide else "h")
        await j.shot("buoy-charts")


@pytest.mark.parametrize("size", EXTRA_SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
async def test_every_screen_at_the_large_and_tall_sizes(journey, size) -> None:
    async with journey(size) as j:
        await j.shot("dashboard")
        for key, step in (("O", "outlook"), ("w", "watchlist"), ("A", "alerts")):
            await j.keys(key)
            await j.shot(step, footer=key != "A")
            await j.keys("escape")
        await j.keys("enter")
        for number, step in (("1", "summary"), ("2", "forecast"), ("7", "buoys"), ("9", "graphics")):
            await j.keys(number)
            await j.shot(f"detail-{step}")
        await j.keys("7", "enter")
        await j.shot("buoy-charts")
        await j.keys("escape", "escape", "question_mark")
        await j.shot("help", footer=False)
        await j.keys("escape", "S")
        await j.shot("settings", footer=False)
        await j.keys("escape")


async def test_resize_across_the_layout_thresholds(journey) -> None:
    async with journey((200, 50)) as j:
        await j.shot("200x50")
        steps = [(120, 30, False, False), (109, 30, True, False), (89, 30, True, True), (80, 24, True, True)]
        for width, height, narrow, compact in steps:
            await j.resize(width, height)
            dash = j.screen
            assert isinstance(dash, DashboardScreen)
            assert dash.has_class("narrow") is narrow and dash.has_class("compact") is compact
            j.see("ERIN")
            await j.shot(f"{width}x{height}")
        await j.resize(280, 70)
        assert not j.screen.has_class("narrow")
        await j.shot("280x70")


async def test_live_resize_through_too_small_and_back(journey) -> None:
    async with journey((120, 30)) as j:
        await j.keys("enter", "7")  # a deeper screen, to prove the stack survives
        await j.shot("before")
        j.expect_small = True
        await j.resize(59, 24)
        assert isinstance(j.screen, TooSmallScreen)
        await j.shot("narrow-too-small", footer=False)
        await j.resize(80, 15)
        assert isinstance(j.screen, TooSmallScreen)
        await j.shot("short-too-small", footer=False)
        j.expect_small = False
        await j.resize(60, 16)
        assert not isinstance(j.screen, TooSmallScreen)
        await j.shot("floor", footer=False)
        await j.resize(120, 30)
        j.see("ERIN")
        await j.shot("restored", footer=False)


@pytest.mark.parametrize(
    "keys",
    [
        pytest.param(("enter",), id="detail"),
        pytest.param(("w",), id="watchlist"),
        pytest.param(("O",), id="outlook"),
        pytest.param(("g",), id="graphics", marks=pytest.mark.xfail(strict=True, reason="#36")),
    ],
)
async def test_status_row_follows_a_resize(journey, monkeypatch, keys) -> None:
    monkeypatch.setattr(EyewallApp, "_pulse", lambda self: None)  # the 1 s clock would repair the row by itself
    async with journey((120, 30)) as j:
        await j.keys(*keys)
        j.expect_small = True
        await j.resize(59, 24)
        j.expect_small = False
        await j.resize(60, 16)  # below 70 columns the row drops its key list and `? help`
        await j.resize(120, 30)
        await j.shot("after-resize")


@pytest.mark.parametrize("small", [(59, 24), (80, 15), (40, 12), (24, 6)], ids=lambda s: f"{s[0]}x{s[1]}")
@pytest.mark.parametrize("make", [replay_app, scripted_app], ids=["replay", "quiet"])
async def test_too_small_shows_the_notice(journey, small, make) -> None:
    async with journey(small, app=make(), storm=False, name=f"too-small-{make.__name__}") as j:
        j.expect_small = True
        assert isinstance(j.screen, TooSmallScreen)
        j.see("Needs at least 60x16")
        await j.shot("notice", footer=False)
        await j.keys("question_mark", "S", "O")  # keys must not crash it
        await j.shot("after-keys", footer=False)
        j.expect_small = False


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "eyewall", *args], capture_output=True, text=True, timeout=120, encoding="utf-8"
    )


def test_cli_version() -> None:
    result = run_cli("--version")
    assert result.returncode == 0 and result.stdout.startswith("eyewall ")


def test_cli_selftest() -> None:
    result = run_cli("--selftest")
    assert result.returncode == 0, result.stderr
    assert "selftest ok" in result.stdout


def test_cli_headless_replay_until() -> None:
    result = run_cli("--demo", "--headless", "--until", "+1h", "--no-config")
    assert result.returncode == 0, result.stderr
    assert "3 event(s)" in result.stderr
    assert len(result.stdout.strip().splitlines()) == 3


def test_cli_headless_rejects_a_bad_until() -> None:
    result = run_cli("--demo", "--headless", "--until", "whenever", "--no-config")
    assert result.returncode == 2 and "eyewall:" in result.stderr


def test_sizes_are_the_agreed_ones() -> None:
    assert SIZES == [(80, 24), (120, 30)] and EXTRA_SIZES == [(100, 50), (200, 50), (280, 70)]


@pytest.mark.xfail(strict=True, reason="#33")
async def test_no_colour_mode_does_not_crash(journey, monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    async with journey((120, 30), app=gallery_app()) as j:
        assert j.app.no_color
        await j.keys("g")
        await gallery_ready(j, "Cone, 5 day")
        await j.shot("graphics-without-colour")
        await j.keys("escape", "b", "enter")
        await j.shot("charts-without-colour")
