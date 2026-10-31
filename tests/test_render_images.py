"""Image decoding limits, frame stepping and the fallback pipeline, on small generated images (no network, no terminal)."""

from __future__ import annotations

import io
import subprocess
import sys

import httpx
import pytest
import respx
from PIL import Image

from eyewall.net import HttpError, RateLimited, new_client
from eyewall.render import images
from eyewall.render.canvas import Mode, Style
from eyewall.render.images import (
    Depth,
    FrameCursor,
    Frames,
    ImageError,
    autocrop,
    check_image_bytes,
    crop_cone,
    fetch_image,
    fit_cells,
    is_noaa_url,
    quantize,
    render_fallback,
    sniff,
)

RED, GREEN, BLUE, WHITE, BLACK = (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255), (0, 0, 0)


def png(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def gif(count: int, size: tuple[int, int] = (4, 4), duration: int = 50) -> bytes:
    frames = [Image.new("RGB", size, (i * 5 % 256, 100, 50)) for i in range(count)]
    out = io.BytesIO()
    frames[0].save(out, "GIF", save_all=True, append_images=frames[1:], duration=duration, loop=0)
    return out.getvalue()


def pixels(rows: list[list[tuple[int, int, int]]]) -> Image.Image:
    img = Image.new("RGB", (len(rows[0]), len(rows)))
    for y, row in enumerate(rows):
        for x, color in enumerate(row):
            img.putpixel((x, y), color)
    return img


# ---- fetching -----------------------------------------------------------------------------------------------------


def test_sniff_reads_the_magic_bytes_not_the_name() -> None:
    assert sniff(png(Image.new("RGB", (2, 2)))) == "png"
    assert sniff(gif(2)) == "gif"
    assert sniff(b"\xff\xd8\xff\xe0 jpeg") == "jpeg"
    assert sniff(b"<html>not ready</html>") is None


def test_image_bytes_over_the_cap_or_not_images_are_refused() -> None:
    with pytest.raises(ImageError, match="limit"):
        check_image_bytes("x", png(Image.new("RGB", (2, 2))), max_bytes=10)
    with pytest.raises(ImageError, match="PNG, GIF or JPEG"):
        check_image_bytes("x", b"<html></html>")


@respx.mock
async def test_fetch_image_sends_the_user_agent_and_checks_the_answer() -> None:
    route = respx.get("https://www.nhc.noaa.gov/cone.png").respond(200, content=png(Image.new("RGB", (3, 3))))
    respx.get("https://www.nhc.noaa.gov/page.png").respond(200, content=b"<html>soft 404</html>")
    respx.get("https://www.nhc.noaa.gov/gone.png").respond(404)
    async with new_client() as client:
        assert sniff(await fetch_image(client, "https://www.nhc.noaa.gov/cone.png")) == "png"
        assert route.calls.last.request.headers["User-Agent"].startswith("eyewall/")
        with pytest.raises(ImageError):
            await fetch_image(client, "https://www.nhc.noaa.gov/page.png")
        with pytest.raises(HttpError):
            await fetch_image(client, "https://www.nhc.noaa.gov/gone.png")
        with pytest.raises(ImageError, match="NOAA"):
            await fetch_image(client, "file:///etc/passwd")


# ---- frames -------------------------------------------------------------------------------------------------------


def test_a_still_has_one_frame_and_does_not_animate() -> None:
    frames = Frames(png(pixels([[RED, GREEN], [BLUE, WHITE]])))
    assert (frames.count, frames.animated, frames.size) == (1, False, (2, 2))
    assert frames.frame(0).getpixel((1, 0)) == GREEN
    assert frames.frame(7).size == (2, 2)  # an index wraps


def test_a_gif_decodes_a_few_frames_at_a_time() -> None:
    frames = Frames(gif(20), cache_size=3)
    assert (frames.count, frames.animated) == (20, True)
    for index in range(20):
        assert frames.frame(index).getpixel((0, 0))[0] == index * 5 % 256
    assert len(frames._cache) == 3  # the rest were dropped as the loop moved on


def test_a_long_loop_is_thinned_to_the_frame_cap() -> None:
    frames = Frames(gif(images.MAX_FRAMES * 2 + 10, size=(2, 2)))
    assert frames.count <= images.MAX_FRAMES


def test_the_frame_interval_follows_the_file_but_never_beats_ten_per_second() -> None:
    assert Frames(gif(2, duration=500)).interval == pytest.approx(0.5)
    assert Frames(gif(2, duration=10)).interval == pytest.approx(0.1)


def test_a_huge_or_broken_image_is_refused_before_it_is_decoded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(images, "MAX_PIXELS", 10)
    with pytest.raises(ImageError, match="size"):
        Frames(png(Image.new("RGB", (4, 4))))
    monkeypatch.undo()
    with pytest.raises(ImageError):
        Frames(b"\x89PNG\r\n\x1a\nnot really")
    with pytest.raises(ImageError):
        Frames(b"")


def test_transparency_is_laid_over_white() -> None:
    img = Image.new("RGBA", (2, 1), (0, 0, 0, 0))
    img.putpixel((1, 0), (255, 0, 0, 255))
    assert Frames(png(img)).frame(0).getpixel((0, 0)) == WHITE


def test_the_cursor_steps_wraps_and_pauses() -> None:
    cursor = FrameCursor(4)
    assert cursor.playing
    assert [cursor.advance() for _ in range(5)] == [1, 2, 3, 0, 1]
    assert cursor.step(-2) == 3  # stepping back wraps, and pauses
    assert not cursor.playing
    assert cursor.advance() == 3  # a paused loop stays put
    assert cursor.step(1) == 0
    assert cursor.toggle() is True
    assert cursor.advance() == 1


def test_a_still_never_plays() -> None:
    cursor = FrameCursor(1)
    assert not cursor.playing
    assert cursor.toggle() is False
    assert cursor.advance() == 0


# ---- the fallback pipeline ----------------------------------------------------------------------------------------


def test_colors_quantize_to_the_terminal_depth() -> None:
    assert quantize((12, 200, 99), Depth.TRUE) == "#0cc863"
    assert quantize((12, 200, 99), Depth.MONO) is None
    assert quantize((250, 10, 10), Depth.C256) == "#ff0000"
    assert quantize((130, 130, 130), Depth.C256) == "#808080"  # the gray ramp is nearer than the color cube
    assert quantize((250, 10, 10), Depth.C16) == "#ff0000"
    assert quantize((120, 5, 5), Depth.C16) == "#800000"


def test_the_depth_comes_from_rich() -> None:
    assert [Depth.from_rich(s) for s in ("truecolor", "256", "standard", "windows", None)] == [
        Depth.TRUE,
        Depth.C256,
        Depth.C16,
        Depth.C16,
        Depth.MONO,
    ]


def test_half_blocks_color_the_top_and_bottom_of_each_cell() -> None:
    img = pixels([[RED, GREEN, BLUE, WHITE], [BLACK, BLACK, BLACK, BLACK], [RED, RED, GREEN, GREEN], [BLACK] * 4])
    frame = render_fallback(img, 4, 2, Mode.HALF, Depth.TRUE, sharpen=False)
    assert (frame.width, frame.height) == (4, 2)
    assert frame.rows[0] == (
        ("▀", Style("#ff0000", "#000000")),
        ("▀", Style("#00ff00", "#000000")),
        ("▀", Style("#0000ff", "#000000")),
        ("▀", Style("#ffffff", "#000000")),
    )
    assert frame.rows[1] == (
        ("▀▀", Style("#ff0000", "#000000")),
        ("▀▀", Style("#00ff00", "#000000")),
    )


def test_a_flat_half_block_cell_is_a_space_with_a_background() -> None:
    img = pixels([[RED, RED], [RED, RED], [BLACK, BLACK], [WHITE, WHITE]])
    frame = render_fallback(img, 2, 2, Mode.HALF, Depth.TRUE, sharpen=False)
    assert frame.rows[0] == (("  ", Style(None, "#ff0000")),)  # neighbours with one style share a run


def test_braille_draws_dots_and_flat_areas_as_color() -> None:
    # a 2 by 4 block: left column bright, right column dark -> the four left dots
    img = pixels([[WHITE, BLACK]] * 4)
    frame = render_fallback(img, 1, 1, Mode.BRAILLE, Depth.TRUE, sharpen=False)
    assert frame.text() == chr(0x2800 + 0x01 + 0x02 + 0x04 + 0x40)
    assert frame.rows[0][0][1] == Style("#ffffff", "#000000")
    flat = render_fallback(pixels([[WHITE, WHITE]] * 4), 1, 1, Mode.BRAILLE, Depth.TRUE, sharpen=False)
    assert flat.rows[0] == ((" ", Style(None, "#ffffff")),)


def test_ascii_picks_a_character_by_brightness_and_only_colors_when_it_can() -> None:
    img = pixels([[BLACK, WHITE], [BLACK, WHITE]])
    frame = render_fallback(img, 2, 1, Mode.ASCII, Depth.MONO, sharpen=False)
    assert frame.text() == " @"
    assert all(style == Style() for _, style in frame.rows[0])
    colored = render_fallback(img, 2, 1, Mode.ASCII, Depth.TRUE, sharpen=False)
    assert colored.rows[0][-1][1].fg == "#ffffff"


def test_the_picture_fits_the_area_and_keeps_its_shape() -> None:
    assert fit_cells((1000, 1000), 80, 24, Mode.HALF) == (48, 24)  # a half-block cell is one pixel wide, two tall
    assert fit_cells((1000, 500), 80, 24, Mode.HALF) == (80, 20)
    assert fit_cells((1000, 1000), 80, 24, Mode.BRAILLE) == (48, 24)  # a braille cell is two pixels wide, four tall
    assert fit_cells((1000, 500), 200, 24, Mode.HALF) == (96, 24)
    assert fit_cells((10, 10), 1, 1, Mode.ASCII) == (1, 1)
    img = Image.new("RGB", (897, 736), (30, 90, 160))
    frame = render_fallback(img, 80, 24, Mode.HALF, Depth.C256)
    assert frame.height <= 24 and frame.width <= 80
    assert all(sum(len(text) for text, _ in row) == frame.width for row in frame.rows)


def test_the_pipeline_is_deterministic() -> None:
    img = Image.effect_mandelbrot((60, 40), (-2.0, -1.0, 1.0, 1.0), 20)
    first = render_fallback(img, 20, 6, Mode.HALF, Depth.C256)
    second = render_fallback(img.copy(), 20, 6, Mode.HALF, Depth.C256)
    assert first == second
    assert (first.width, first.height) == (18, 6)


def test_an_empty_area_draws_nothing() -> None:
    assert render_fallback(Image.new("RGB", (4, 4)), 0, 5).rows == ()


def test_a_uniform_border_is_trimmed() -> None:
    img = Image.new("RGB", (100, 80), WHITE)
    img.paste(Image.new("RGB", (60, 40), BLUE), (20, 20))
    assert autocrop(img).size == (60, 40)
    assert autocrop(Image.new("RGB", (10, 10), WHITE)).size == (10, 10)  # nothing but border: left alone


def test_the_cone_crop_drops_the_legend_only_from_a_cone_shaped_image() -> None:
    cone = Image.new("RGB", (897, 736), (120, 160, 200))
    cropped = crop_cone(cone)
    assert cropped.size[0] < 897 and cropped.size[1] < 736 * 0.78
    other = Image.new("RGB", (500, 500), WHITE)
    other.paste(Image.new("RGB", (200, 200), RED), (100, 100))
    assert crop_cone(other).size == (200, 200)  # not cone-shaped: only its plain border goes


# ---- the lazy import rule -----------------------------------------------------------------------------------------


def test_importing_the_core_does_not_import_textual_image() -> None:
    code = (
        "import sys\n"
        "import eyewall.app, eyewall.cli, eyewall.render.images, eyewall.ui.widgets.gallery, eyewall.ui.screens.graphics\n"
        "from eyewall.render.images import load_inline\n"
        "assert load_inline('never') is None\n"
        "assert load_inline('auto') is None  # stdout is a pipe here\n"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] == 'textual_image')\n"
        "assert not bad, bad\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr


def test_the_source_tree_imports_textual_image_in_one_place_only() -> None:
    import re
    from pathlib import Path

    root = Path(images.__file__).resolve().parents[1]
    pattern = re.compile(r"^\s*(?:from|import)\s+textual_image", re.MULTILINE)
    users = sorted(p.name for p in root.rglob("*.py") if pattern.search(p.read_text(encoding="utf-8")))
    assert users == ["images.py"]


def test_the_recorded_cone_draws_in_every_mode_without_its_legend() -> None:
    from pathlib import Path

    path = Path(__file__).parent / "fixtures" / "replay" / "erin2025" / "graphics" / "cone_038.png"
    img = Image.open(path).convert("RGB")
    for mode, depth in ((Mode.HALF, Depth.TRUE), (Mode.BRAILLE, Depth.C256), (Mode.ASCII, Depth.MONO)):
        frame = render_fallback(img, 100, 30, mode, depth, cone=True)
        assert 0 < frame.height <= 30 and 0 < frame.width <= 100
        assert frame.text().strip()
    half = render_fallback(img, 100, 60, Mode.HALF, Depth.TRUE, cone=True)
    full = render_fallback(img, 100, 60, Mode.HALF, Depth.TRUE, cone=False)
    assert half.width == full.width == 100 and half.height < full.height  # the legend block is gone


def test_limited_palettes_remember_their_nearest_colour() -> None:
    from eyewall.render.images import Depth, _snap, quantize

    _snap.cache_clear()
    for _ in range(3):
        assert quantize((12, 200, 77), Depth.C256) == quantize((12, 200, 77), Depth.C256)
        assert quantize((12, 200, 77), Depth.C16) is not None
    info = _snap.cache_info()
    assert info.misses == 2 and info.hits == 7


# ---- downloads stay on https NOAA hosts ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://www.nhc.noaa.gov/x.png",
        "https://noaa.gov.evil.com/x.png",
        "https://noaa.gov@evil.com/x.png",
        "https://user@www.nhc.noaa.gov/x.png",
        "https://evil.com\\@noaa.gov/x.png",
        "https://noaa.gov\\.evil.com/x.png",
        "https://evilnoaa.gov/x.png",
        "https://www.nhc.noaa.gov:8443/x.png",
        "https://www.nhc.noaa.gov/x .png",
        "https://www.nhc.noaa.gov/\nx.png",
        "ftp://www.nhc.noaa.gov/x.png",
        "//www.nhc.noaa.gov/x.png",
        "",
    ],
)
def test_is_noaa_url_refuses_lookalikes_and_other_schemes(url: str) -> None:
    assert is_noaa_url(url) is False


@pytest.mark.parametrize(
    "url", ["https://www.nhc.noaa.gov/x.png", "https://WWW.NOAA.GOV/x", "https://forecast.weather.gov:443/x"]
)
def test_is_noaa_url_accepts_https_noaa_hosts(url: str) -> None:
    assert is_noaa_url(url) is True


@respx.mock
async def test_fetch_image_refuses_other_hosts_and_http_without_sending_a_request() -> None:
    route = respx.route().respond(200, content=png(Image.new("RGB", (2, 2))))
    async with new_client() as client:
        for url in ("https://example.test/a.png", "http://www.nhc.noaa.gov/a.png", "https://noaa.gov.evil.com/a.png"):
            with pytest.raises(ImageError, match="NOAA"):
                await fetch_image(client, url)
    assert not route.called


@respx.mock
async def test_fetch_image_follows_a_redirect_inside_noaa_and_refuses_one_that_leaves() -> None:
    body = png(Image.new("RGB", (2, 2)))
    respx.get("https://www.nhc.noaa.gov/old.png").respond(302, headers={"Location": "/new.png"})
    respx.get("https://www.nhc.noaa.gov/new.png").respond(200, content=body)
    respx.get("https://www.nhc.noaa.gov/to-http.png").respond(
        301, headers={"Location": "http://www.nhc.noaa.gov/a.png"}
    )
    respx.get("https://www.nhc.noaa.gov/away.png").respond(301, headers={"Location": "https://example.test/a.png"})
    respx.get("https://www.nhc.noaa.gov/loop.png").respond(302, headers={"Location": "/loop.png"})
    other = respx.get("https://example.test/a.png").respond(200, content=body)
    async with new_client() as client:
        assert await fetch_image(client, "https://www.nhc.noaa.gov/old.png") == body
        for name in ("to-http", "away"):
            with pytest.raises(ImageError, match="NOAA"):
                await fetch_image(client, f"https://www.nhc.noaa.gov/{name}.png")
        with pytest.raises(ImageError, match="redirects"):
            await fetch_image(client, "https://www.nhc.noaa.gov/loop.png")
    assert not other.called


async def _no_sleep(seconds: float) -> None:
    _SLEPT.append(seconds)


_SLEPT: list[float] = []


@respx.mock
async def test_fetch_image_retries_a_503_and_a_dropped_connection_then_succeeds() -> None:
    _SLEPT.clear()
    body = png(Image.new("RGB", (2, 2)))
    url = "https://www.nhc.noaa.gov/retry.png"
    route = respx.get(url).mock(
        side_effect=[
            httpx.Response(503, content=b"busy"),
            httpx.ConnectError("reset"),
            httpx.Response(200, content=body),
        ]
    )
    async with new_client() as client:
        assert await fetch_image(client, url, sleep=_no_sleep) == body
    assert route.call_count == 3 and _SLEPT == [1.0, 2.0]


@respx.mock
async def test_fetch_image_gives_up_after_two_retries_and_caps_retry_after() -> None:
    _SLEPT.clear()
    url = "https://www.nhc.noaa.gov/down.png"
    route = respx.get(url).respond(503, headers={"Retry-After": "9999"}, content=b"x" * 100)
    async with new_client() as client:
        with pytest.raises(HttpError):
            await fetch_image(client, url, sleep=_no_sleep)
    assert route.call_count == 3 and _SLEPT == [30.0, 30.0]
    limited = respx.get("https://www.nhc.noaa.gov/slow.png").respond(429)
    async with new_client() as client:
        with pytest.raises(RateLimited):
            await fetch_image(client, "https://www.nhc.noaa.gov/slow.png", sleep=_no_sleep)
    assert limited.call_count == 3


@respx.mock
async def test_fetch_image_does_not_retry_a_404_or_a_redirect_to_another_host() -> None:
    _SLEPT.clear()
    gone = respx.get("https://www.nhc.noaa.gov/gone2.png").respond(404)
    respx.get("https://www.nhc.noaa.gov/away2.png").respond(302, headers={"Location": "https://evil.example/a.png"})
    async with new_client() as client:
        with pytest.raises(HttpError):
            await fetch_image(client, "https://www.nhc.noaa.gov/gone2.png", sleep=_no_sleep)
        with pytest.raises(ImageError, match="NOAA"):
            await fetch_image(client, "https://www.nhc.noaa.gov/away2.png", sleep=_no_sleep)
    assert gone.call_count == 1 and _SLEPT == []
