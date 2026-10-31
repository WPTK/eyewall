"""Images in the terminal: fetch, decode lazily, and draw a readable approximation when the terminal has no graphics.

Two display paths share this module's decoding:

- Inline: Sixel or the Kitty graphics protocol through `textual-image`, when the terminal supports it. `load_inline`
  is the only place that imports `textual_image`, because importing it with stdout on a TTY sends terminal queries and
  those must be answered before Textual takes the terminal. The app calls it once, before it starts; nothing else
  does, and no test does.
- The fallback: `render_fallback` downsamples with LANCZOS to the cell grid times two (half blocks, ASCII) or times
  (2, 4) (braille), sharpens a little, stretches the contrast, quantizes to the terminal's color depth and returns rows
  of (text, Style) runs. It is a pure function of the pixels, so a small test image gives the same cells everywhere.

Nothing here imports Textual. Downloaded images are capped in bytes, pixels and frames, and a loop is decoded one frame
at a time with a few frames kept (`Frames`).
"""

from __future__ import annotations

import io
import math
import sys
from collections import OrderedDict
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

import httpx
from PIL import Image as PILImage
from PIL import ImageChops, ImageFilter, ImageOps

from eyewall.net import fetch_bytes
from eyewall.render.canvas import Mode, Run, Style

MAX_IMAGE_BYTES = 24 * 1024 * 1024  # the full GEOCOLOR loop of a long storm is about 13 MB
MAX_PIXELS = 36_000_000  # per frame; the satellite loops are 1000 by 1000
MAX_FRAMES = 240  # a longer loop is thinned to at most this many frames
FRAME_CACHE = 6  # decoded frames kept per image
MAX_FPS = 10.0
MIN_FRAME_SECONDS = 1.0 / MAX_FPS

# The NHC cone graphic is 897 by 736 with a white border, and a legend block under the map that starts at 78% of the
# height. Left, top, right and bottom as fractions of the image; used only when the aspect ratio matches.
CONE_ASPECT = 897 / 736
CONE_ASPECT_TOLERANCE = 0.15
CONE_MARGINS = (0.012, 0.012, 0.012, 0.225)

CONTRAST_CUTOFF = 1  # percent of pixels ignored at each end when stretching the contrast
SHARPEN = ImageFilter.UnsharpMask(radius=1.0, percent=50, threshold=3)
BRAILLE_FLAT = 32  # a braille block whose luminance range is below this is drawn as a plain color
ASCII_RAMP = " .:-=+*#%@"

# Index is dy * 2 + dx within a braille cell: the dot bits go down the left column (1, 2, 3, 7), then the right.
_BRAILLE_BITS = (0x01, 0x08, 0x02, 0x10, 0x04, 0x20, 0x40, 0x80)


class ImageError(Exception):
    """An image that cannot be shown: too big, not an image, or damaged."""


# ---- fetching and decoding --------------------------------------------------------------------------------------


def sniff(data: bytes) -> str | None:
    """`png`, `gif` or `jpeg` from the first bytes, or None. The server's content type is not trusted."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    return None


def check_image_bytes(url: str, data: bytes, max_bytes: int = MAX_IMAGE_BYTES) -> bytes:
    if len(data) > max_bytes:
        raise ImageError(f"{url}: {len(data) // (1024 * 1024)} MB is over the {max_bytes // (1024 * 1024)} MB limit")
    if sniff(data) is None:
        raise ImageError(f"{url}: the server did not send a PNG, GIF or JPEG")
    return data


async def fetch_image(client: httpx.AsyncClient, url: str, *, max_bytes: int = MAX_IMAGE_BYTES) -> bytes:
    """GET an image through eyewall's HTTP client (User-Agent, timeouts, and the cache's conditional requests).

    Raises `eyewall.net.FetchError` when the request fails and `ImageError` when the answer is not a usable image.
    """
    if urlsplit(url).scheme not in ("http", "https"):
        raise ImageError(f"{url}: not a web address")
    fetched = await fetch_bytes(client, url)
    return check_image_bytes(url, fetched.body, max_bytes)


class Frames:
    """An opened image whose frames are decoded one at a time.

    A still has one frame. An animated GIF is thinned to at most `MAX_FRAMES` frames, and only `cache_size` decoded
    frames are kept, so a long loop costs the compressed bytes plus a few frames of pixels.
    """

    def __init__(self, data: bytes, *, cache_size: int = FRAME_CACHE) -> None:
        try:
            self._image = PILImage.open(io.BytesIO(data))
        except (OSError, ValueError, SyntaxError, PILImage.DecompressionBombError) as exc:
            raise ImageError(f"not a readable image ({exc})") from exc
        width, height = self._image.size
        if width < 1 or height < 1 or width * height > MAX_PIXELS:
            raise ImageError(f"{width} by {height} pixels is not a size eyewall will decode")
        total = max(1, int(getattr(self._image, "n_frames", 1)))
        stride = max(1, math.ceil(total / MAX_FRAMES))
        self._indices = tuple(range(0, total, stride))
        self._cache: OrderedDict[int, PILImage.Image] = OrderedDict()
        self._cache_size = max(1, cache_size)
        self.size = (width, height)
        self.format = sniff(data)
        self._interval = self._first_interval()

    def _first_interval(self) -> float:
        try:
            ms = float(self._image.info.get("duration", 0) or 0)
        except (TypeError, ValueError):
            ms = 0.0
        return max(MIN_FRAME_SECONDS, ms / 1000.0)

    @property
    def count(self) -> int:
        return len(self._indices)

    @property
    def animated(self) -> bool:
        return self.count > 1

    @property
    def interval(self) -> float:
        """Seconds between frames: the file's own pace, never faster than `MAX_FPS`."""
        return self._interval

    def frame(self, index: int) -> PILImage.Image:
        """Frame `index` (wrapped into range) as RGB on white, decoding it only if it is not among the recent ones."""
        index %= self.count
        if index in self._cache:
            self._cache.move_to_end(index)
            return self._cache[index]
        try:
            self._image.seek(self._indices[index])
            rgb = _flatten(self._image)
        except (OSError, ValueError, EOFError, SyntaxError, PILImage.DecompressionBombError) as exc:
            raise ImageError(f"frame {index + 1} cannot be decoded ({exc})") from exc
        self._cache[index] = rgb
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return rgb

    def close(self) -> None:
        self._cache.clear()
        self._image.close()


def _flatten(frame: PILImage.Image) -> PILImage.Image:
    """RGB with any transparency laid over white."""
    if frame.mode in ("RGBA", "LA") or "transparency" in frame.info:
        rgba = frame.convert("RGBA")
        base = PILImage.new("RGB", rgba.size, (255, 255, 255))
        base.paste(rgba, mask=rgba.getchannel("A"))
        return base
    return frame.convert("RGB")


class FrameCursor:
    """Which frame of a loop is showing, and whether it is playing. Stepping pauses, like a video player's."""

    def __init__(self, count: int, *, playing: bool = True) -> None:
        self.count = max(1, count)
        self.index = 0
        self.playing = playing and self.count > 1

    def advance(self) -> int:
        """The next frame of a playing loop, wrapping at the end."""
        if self.playing:
            self.index = (self.index + 1) % self.count
        return self.index

    def step(self, delta: int) -> int:
        """Move by `delta` frames (wrapping) and pause."""
        self.playing = False
        self.index = (self.index + delta) % self.count
        return self.index

    def toggle(self) -> bool:
        if self.count > 1:
            self.playing = not self.playing
        return self.playing


# ---- the fallback pipeline --------------------------------------------------------------------------------------


class Depth(StrEnum):
    """How many colors the terminal can show."""

    TRUE = "truecolor"
    C256 = "256"
    C16 = "16"
    MONO = "mono"

    @classmethod
    def from_rich(cls, color_system: str | None) -> Depth:
        """From `rich.console.Console.color_system`: truecolor, 256, standard, windows or None."""
        return {"truecolor": cls.TRUE, "256": cls.C256, "standard": cls.C16, "windows": cls.C16}.get(
            color_system or "", cls.MONO
        )


_CUBE = (0, 95, 135, 175, 215, 255)
_ANSI16 = (
    (0, 0, 0),
    (128, 0, 0),
    (0, 128, 0),
    (128, 128, 0),
    (0, 0, 128),
    (128, 0, 128),
    (0, 128, 128),
    (192, 192, 192),
    (128, 128, 128),
    (255, 0, 0),
    (0, 255, 0),
    (255, 255, 0),
    (0, 0, 255),
    (255, 0, 255),
    (0, 255, 255),
    (255, 255, 255),
)

RGB = tuple[int, int, int]


def _nearest(rgb: RGB, palette: tuple[RGB, ...]) -> RGB:
    r, g, b = rgb
    return min(palette, key=lambda p: (p[0] - r) ** 2 + (p[1] - g) ** 2 + (p[2] - b) ** 2)


@lru_cache(maxsize=1 << 17)
def _snap(rgb: RGB, depth: Depth) -> RGB:
    """The palette color nearest to `rgb` at a limited depth; remembered, because images repeat their colors."""
    return _nearest(rgb, _XTERM_256 if depth is Depth.C256 else _ANSI16)


_XTERM_256 = tuple((r, g, b) for r in _CUBE for g in _CUBE for b in _CUBE) + tuple((v, v, v) for v in range(8, 239, 10))


def quantize(rgb: RGB, depth: Depth) -> str | None:
    """A `#rrggbb` color the terminal can show at that depth (the nearest palette entry), or None for mono."""
    if depth is Depth.MONO:
        return None
    if depth is Depth.C256 or depth is Depth.C16:
        rgb = _snap(rgb, depth)
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def luminance(rgb: RGB) -> int:
    return (299 * rgb[0] + 587 * rgb[1] + 114 * rgb[2]) // 1000


def _mean(pixels: list[RGB]) -> RGB:
    n = len(pixels)
    return (sum(p[0] for p in pixels) // n, sum(p[1] for p in pixels) // n, sum(p[2] for p in pixels) // n)


def autocrop(img: PILImage.Image, tolerance: int = 10) -> PILImage.Image:
    """Trim a uniform border (the color of the corner pixel), keeping at least a quarter of each side."""
    rgb = img.convert("RGB")
    corner: Any = rgb.getpixel((0, 0))
    difference = ImageChops.difference(rgb, PILImage.new("RGB", rgb.size, corner)).convert("L")
    box = difference.point(lambda v: 255 if v > tolerance else 0).getbbox()
    if box is None:
        return rgb
    width, height = rgb.size
    left, top, right, bottom = box
    if (right - left) * 4 < width or (bottom - top) * 4 < height:
        return rgb
    return rgb.crop(box)


def crop_cone(img: PILImage.Image) -> PILImage.Image:
    """Cut the border and the legend block off an NHC cone graphic; any other shape only loses its uniform border."""
    width, height = img.size
    if abs(width / height - CONE_ASPECT) / CONE_ASPECT <= CONE_ASPECT_TOLERANCE:
        left, top, right, bottom = CONE_MARGINS
        return img.crop(
            (round(width * left), round(height * top), round(width * (1 - right)), round(height * (1 - bottom)))
        )
    return autocrop(img)


@dataclass(frozen=True, slots=True)
class FallbackFrame:
    """An image drawn in terminal cells: rows of (text, Style) runs, all `width` cells wide."""

    rows: tuple[tuple[Run, ...], ...]
    width: int
    height: int

    def text(self) -> str:
        return "\n".join("".join(text for text, _ in row) for row in self.rows)


def _cell_pixels(mode: Mode) -> tuple[int, int]:
    return (2, 4) if mode is Mode.BRAILLE else (1, 2)


def fit_cells(size: tuple[int, int], cols: int, rows: int, mode: Mode) -> tuple[int, int]:
    """Cells an image of that size takes when scaled to fit `cols` by `rows`, keeping its shape (pixels are square)."""
    dx, dy = _cell_pixels(mode)
    width, height = size
    scale = min(cols * dx / width, rows * dy / height)
    return (max(1, min(cols, round(width * scale / dx))), max(1, min(rows, round(height * scale / dy))))


def prepare(img: PILImage.Image, cols: int, rows: int, mode: Mode, *, sharpen: bool = True) -> PILImage.Image:
    """Resize to the cell grid (LANCZOS), apply a mild unsharp mask and stretch the contrast."""
    cells_w, cells_h = fit_cells(img.size, cols, rows, mode)
    dx, dy = _cell_pixels(mode)
    small = img.convert("RGB").resize((cells_w * dx, cells_h * dy), PILImage.Resampling.LANCZOS)
    if sharpen:
        small = small.filter(SHARPEN)
    return ImageOps.autocontrast(small, cutoff=CONTRAST_CUTOFF)


def _merge(cells: list[tuple[str, Style]]) -> tuple[Run, ...]:
    runs: list[Run] = []
    for ch, style in cells:
        if runs and runs[-1][1] == style:
            runs[-1] = (runs[-1][0] + ch, style)
        else:
            runs.append((ch, style))
    return tuple(runs)


def render_fallback(
    img: PILImage.Image,
    cols: int,
    rows: int,
    mode: Mode = Mode.HALF,
    depth: Depth = Depth.TRUE,
    *,
    cone: bool = False,
    sharpen: bool = True,
) -> FallbackFrame:
    """Draw an image in at most `cols` by `rows` cells.

    `Mode.HALF` colors the upper and lower half of each cell, `Mode.BRAILLE` fits 2 by 4 pixels in a cell with a
    foreground and a background, and `Mode.ASCII` picks a character by brightness (colored when the terminal has
    color). `cone` trims the border and legend of an NHC cone graphic first.
    """
    if cols < 1 or rows < 1:
        return FallbackFrame((), 0, 0)
    source = crop_cone(img) if cone else img
    small = prepare(source, cols, rows, mode, sharpen=sharpen)
    dx, dy = _cell_pixels(mode)
    pixels: Any = small.load()
    width, height = small.size[0] // dx, small.size[1] // dy
    out: list[tuple[Run, ...]] = []
    for row in range(height):
        cells: list[tuple[str, Style]] = []
        for col in range(width):
            block = [pixels[col * dx + i, row * dy + j] for j in range(dy) for i in range(dx)]
            if mode is Mode.BRAILLE:
                cells.append(_braille_cell(block, depth))
            elif mode is Mode.HALF:
                cells.append(_half_cell(block[0], block[1], depth))
            else:
                cells.append(_ascii_cell(block, depth))
        out.append(_merge(cells))
    return FallbackFrame(tuple(out), width, height)


def _half_cell(top: RGB, bottom: RGB, depth: Depth) -> tuple[str, Style]:
    if depth is Depth.MONO:
        return (" ▀▄█"[(luminance(top) >= 128) + 2 * (luminance(bottom) >= 128)], Style())
    if quantize(top, depth) == quantize(bottom, depth):
        return (" ", Style(None, quantize(top, depth)))
    return ("▀", Style(quantize(top, depth), quantize(bottom, depth)))


def _ascii_cell(block: list[RGB], depth: Depth) -> tuple[str, Style]:
    average = _mean(block)
    char = ASCII_RAMP[luminance(average) * (len(ASCII_RAMP) - 1) // 255]
    return (char, Style(quantize(average, depth)) if char != " " else Style())


def _braille_cell(block: list[RGB], depth: Depth) -> tuple[str, Style]:
    lums = [luminance(p) for p in block]
    mean = sum(lums) // len(lums)
    if max(lums) - min(lums) < BRAILLE_FLAT:
        average = _mean(block)
        if depth is Depth.MONO:
            return ("⣿", Style()) if mean >= 128 else (" ", Style())
        return (" ", Style(None, quantize(average, depth)))
    lit = [lum > mean for lum in lums]
    mask = sum(_BRAILLE_BITS[i] for i, on in enumerate(lit) if on)
    char = chr(0x2800 + mask) if mask else " "
    if depth is Depth.MONO:
        return (char, Style())
    on = [p for p, flag in zip(block, lit, strict=True) if flag]
    off = [p for p, flag in zip(block, lit, strict=True) if not flag]
    return (char, Style(quantize(_mean(on), depth) if on else None, quantize(_mean(off), depth) if off else None))


# ---- inline graphics --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InlineBackend:
    """A terminal graphics protocol, and the Textual widget class that draws an image with it."""

    kind: str  # "sixel" or "tgp"
    widget: Any


def load_inline(mode: str = "auto") -> InlineBackend | None:
    """Detect Sixel or Kitty graphics support, or None.

    This is the one place `textual_image` is imported. Importing it sends terminal queries when stdout is a terminal, so
    it runs once, before Textual starts, and only when `[graphics] inline` is not "never" and stdout is a terminal. A
    terminal that offers neither protocol gets None, and the caller uses `render_fallback`.
    """
    if mode == "never":
        return None
    stdout = sys.__stdout__
    if stdout is None or not stdout.isatty():
        return None
    try:
        from textual_image.renderable import Image as Renderable
        from textual_image.renderable.sixel import Image as SixelRenderable
        from textual_image.renderable.tgp import Image as TgpRenderable
        from textual_image.widget import Image as Widget
    except Exception:  # a probe or import failure must never stop the app from starting
        return None
    if Renderable is SixelRenderable:
        return InlineBackend("sixel", Widget)
    if Renderable is TgpRenderable:
        return InlineBackend("tgp", Widget)
    return None
