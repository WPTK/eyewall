"""The graphics gallery: a list of a storm's images and the picked one drawn beside it.

The picture is drawn inline (Sixel or Kitty graphics, through `textual-image`) when the app found a terminal that
supports it, and otherwise by the fallback in `render.images`. An image is fetched only when it is picked while the
gallery is on screen, a loop plays only while it is on screen, and every failure ends as a message in the picture area:
nothing raised here reaches the app.
"""

from __future__ import annotations

import asyncio
import logging
import os
import webbrowser
from typing import TYPE_CHECKING, Any, ClassVar

from rich.segment import Segment
from rich.style import Style as RichStyle
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.strip import Strip
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from eyewall.net import FetchError
from eyewall.palette import DIM
from eyewall.render.canvas import Mode
from eyewall.render.images import (
    Depth,
    FallbackFrame,
    FrameCursor,
    Frames,
    ImageError,
    crop_cone,
    inline_wanted,
    render_fallback,
)
from eyewall.ui import nav
from eyewall.ui.gallery import SATELLITE_PRODUCTS, GalleryItem, build_items
from eyewall.ui.widgets.strips import blank, centered
from eyewall.urls import is_noaa_url

if TYPE_CHECKING:
    from eyewall.app import EyewallApp

log = logging.getLogger(__name__)

DEBOUNCE_SECONDS = 0.25  # a key held on the list picks one image, not every image it passes
RENDER_CACHE = 48  # a loop's worth of drawn frames at most; the colour lookups are memoised in render.images


def image_mode(glyph_set: str, depth: Depth) -> Mode:
    """Half blocks keep the most color; braille holds more detail with few colors; ASCII for the legacy set."""
    if glyph_set == "ascii":
        return Mode.ASCII
    return Mode.BRAILLE if depth is Depth.MONO else Mode.HALF


class ImageView(Widget):
    """The fallback picture: a `FallbackFrame` centered in the widget, or a few lines of message."""

    class Resized(Message):
        """The area changed, so the picture has to be drawn again at the new size."""

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._lines: list[Strip] = []
        self._is_picture = False

    def show(self, frame: FallbackFrame) -> None:
        self._lines = [
            Strip([Segment(text, RichStyle(color=s.fg, bgcolor=s.bg)) for text, s in row], frame.width)
            for row in frame.rows
        ]
        self._is_picture = True
        self.refresh()

    def say(self, message: str) -> None:
        self._lines = [Strip([Segment(line, RichStyle(color=DIM))]) for line in message.splitlines() or [""]]
        self._is_picture = False
        self.refresh()

    def on_resize(self, event: events.Resize) -> None:
        self.post_message(self.Resized())

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        # A picture sits under the caption, so a tall area leaves one empty band below it; a message is centered.
        top = 0 if self._is_picture else max(0, (self.size.height - len(self._lines)) // 2)
        index = y - top
        if not 0 <= index < len(self._lines):
            return blank(width)
        return centered(self._lines[index], width)


class GalleryPanel(Vertical, can_focus=True):
    """One storm's images. `set_active` says whether it is on screen; nothing is fetched or played while it is not."""

    NAV_SCOPES = ("gallery",)
    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [*nav.bindings("gallery")]

    def __init__(self, storm_id: str, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.storm_id = storm_id
        self.debounce = DEBOUNCE_SECONDS
        self.active = False
        self.items: list[GalleryItem] = []
        self.current: GalleryItem | None = None
        self._shown: tuple[str, str, str] | None = None  # (key, url, version) of the picture on screen
        self._loading: tuple[str, str, str] | None = None  # the one being fetched
        self._frames: Frames | None = None
        self._cursor: FrameCursor | None = None
        self._timer: Timer | None = None
        self._populating = False
        self._extras_asked = False
        self._rendered: dict[tuple[Any, ...], FallbackFrame] = {}
        self._failed_toast = False
        self._failed: tuple[str, str, str] | None = None  # the picture that last failed to load
        self._inline: Widget | None = None

    @property
    def eye(self) -> EyewallApp:
        return self.app  # type: ignore[return-value]

    # ---- layout -----------------------------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(id="gal-body"):
            yield OptionList(id="gal-list")
            with Vertical(id="gal-main"):
                yield Static("", id="gal-caption")
                yield ImageView(id="gal-view")

    def on_mount(self) -> None:
        self.refresh_data()

    def on_unmount(self) -> None:
        self._stop_timer()
        if self._frames is not None:
            self._frames.close()
            self._frames = None

    @property
    def uses_inline(self) -> bool:
        eye = self.eye
        return eye.inline is not None and inline_wanted(eye.config.graphics.inline, eye.config.map.glyph_set)

    # ---- items ------------------------------------------------------------------------------------------------

    def refresh_data(self) -> None:
        """Rebuild the list from the store. Fetches nothing unless the picked image changed while on screen."""
        state = self.eye.store.storms.get(self.storm_id)
        items = build_items(state, self.eye.floaters_for(self.storm_id)) if state is not None else []
        if [i.key for i in items] != [i.key for i in self.items]:
            self._fill(items)
        else:
            by_key = {i.key: i for i in items}
            self.items = items
            if self.current is not None:
                self.current = by_key.get(self.current.key, self.current)
        self._update_hint()
        if self.active:
            self._ensure_shown()

    def _fill(self, items: list[GalleryItem]) -> None:
        listing = self.query_one("#gal-list", OptionList)
        wanted = self.current.key if self.current is not None else None
        self._populating = True
        try:
            listing.clear_options()
            listing.add_options([Option(_option_text(i), id=i.key) for i in items])
            self.items = items
            keys = [i.key for i in items]
            index = keys.index(wanted) if wanted in keys else 0
            self.current = items[index] if items else None
            if items:
                listing.highlighted = index
        finally:
            self._populating = False
        self._show_list(len(items) > 1)
        if not items:
            self._drop_picture()
            self._say(self._empty_message())

    def _show_list(self, show: bool) -> None:
        """The list is there to choose between pictures; with one (or none) the picture takes the whole width."""
        listing = self.query_one("#gal-list", OptionList)
        had_focus = listing.has_focus
        listing.display = show
        if had_focus and not show:
            self.focus()  # the keys of the gallery belong to the panel; they need focus somewhere inside it

    def focus_list(self) -> None:
        """Put the focus where the gallery's keys work: on the list when it is shown, else on the panel."""
        listing = self.query_one("#gal-list", OptionList)
        (listing if listing.display else self).focus()

    def _empty_message(self) -> str:
        if self.storm_id not in self.eye.store.storms:
            return "This storm is no longer active."
        return "No graphics yet."

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        event.stop()
        if self._populating:
            return
        picked = next((i for i in self.items if i.key == event.option_id), None)
        if picked is not None and picked != self.current:
            self._failed = None  # picking an image again is the way to retry one that failed
            self.current = picked
            self._update_hint()
            if self.active:
                self._ensure_shown()

    # ---- on screen or not -------------------------------------------------------------------------------------

    def set_active(self, active: bool) -> None:
        if active == self.active:
            return
        self.active = active
        if active:
            self._ask_for_extras()
            self._ensure_shown()
            self._restart_timer()
        else:
            self._stop_timer()
            self.workers.cancel_group(self, "gallery-load")
            self._loading = None

    def _ask_for_extras(self) -> None:
        """The other satellite products are listed by NESDIS on demand, so they are asked for only now."""
        if self._extras_asked:
            return
        self._extras_asked = True
        self.run_worker(self._fetch_extras(), group="gallery-extras", exit_on_error=False)

    async def _fetch_extras(self) -> None:
        for code, _ in SATELLITE_PRODUCTS:
            try:
                changed = await self.eye.floater(self.storm_id, code)
            except Exception:
                log.exception("could not list the %s imagery", code)
                continue
            if changed and self.is_attached:
                self.refresh_data()

    # ---- showing the picked image -----------------------------------------------------------------------------

    def _ensure_shown(self) -> None:
        item = self.current
        if item is None:
            return
        if not item.viewable:
            self._drop_picture()
            self._say(
                f"{item.title}\n\nThis is a data file, not a picture.\nPress o to open it or y to copy its address."
            )
            self._update_caption()
            return
        wanted = (item.key, item.url, item.version)
        if (self._shown == wanted and self._frames is not None) or self._loading == wanted or self._failed == wanted:
            return
        self._shown = None
        self._loading = wanted
        self._update_caption(loading=True)
        self._say("Loading...")
        self.run_worker(self._load(item), group="gallery-load", exclusive=True, exit_on_error=False)

    async def _load(self, item: GalleryItem) -> None:
        try:
            await self._fetch_and_show(item)
        finally:
            if self._loading == (item.key, item.url, item.version):
                self._loading = None

    async def _fetch_and_show(self, item: GalleryItem) -> None:
        try:
            if self.debounce:
                await asyncio.sleep(self.debounce)
            data = await self.eye.load_image(item.url, item.version)
            frames = await asyncio.to_thread(_open_frames, data)
        except (FetchError, ImageError) as exc:
            self._failed = (item.key, item.url, item.version)
            self._drop_picture()
            self._say(f"Could not load this image.\n\n{exc}")
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("could not load %s", item.url)
            self._failed = (item.key, item.url, item.version)
            self._drop_picture()
            self._say(f"Could not show this image.\n\n{type(exc).__name__}: {exc}")
            return
        if self.current is None or self.current.key != item.key:
            frames.close()
            return
        self._drop_picture()
        self._frames = frames
        self._cursor = FrameCursor(frames.count, playing=item.loop)
        self._shown = (item.key, item.url, item.version)
        self._paint()
        self._restart_timer()

    def _drop_picture(self) -> None:
        self._stop_timer()
        if self._frames is not None:
            self._frames.close()
        self._frames = None
        self._cursor = None
        self._shown = None
        self._rendered.clear()
        if self._inline is not None:
            self._inline.display = False
        self.query_one("#gal-view", ImageView).display = True

    def _say(self, message: str) -> None:
        self.query_one("#gal-view", ImageView).say(message)

    # ---- painting ---------------------------------------------------------------------------------------------

    def on_image_view_resized(self, event: ImageView.Resized) -> None:
        event.stop()
        if self._frames is not None and not self.uses_inline:
            self._paint()

    def _paint(self) -> None:
        frames, cursor = self._frames, self._cursor
        if frames is None or cursor is None:
            return
        try:
            if self.uses_inline:
                self._paint_inline(frames, cursor)
            else:
                self._paint_fallback(frames, cursor)
        except ImageError as exc:
            self._drop_picture()
            self._say(f"Could not show this image.\n\n{exc}")
            return
        self._update_caption()

    def _paint_fallback(self, frames: Frames, cursor: FrameCursor) -> None:
        view = self.query_one("#gal-view", ImageView)
        view.display = True
        if self._inline is not None:
            self._inline.display = False
        cols, rows = view.size.width, view.size.height
        if cols < 2 or rows < 2:
            return
        eye = self.eye
        depth = eye.color_depth
        mode = image_mode(eye.config.map.glyph_set, depth)
        cone = self.current is not None and self.current.cone
        key = (cursor.index, cols, rows, mode, depth, cone)
        frame = self._rendered.get(key)
        if frame is None:
            frame = render_fallback(frames.frame(cursor.index), cols, rows, mode, depth, cone=cone)
            if len(self._rendered) >= RENDER_CACHE:
                self._rendered.pop(next(iter(self._rendered)))
            self._rendered[key] = frame
        view.show(frame)

    def _paint_inline(self, frames: Frames, cursor: FrameCursor) -> None:
        backend = self.eye.inline
        if backend is None:
            return
        if self._inline is None:
            self._inline = backend.widget(None, id="gal-inline")
            self.query_one("#gal-main", Vertical).mount(self._inline)
        self.query_one("#gal-view", ImageView).display = False
        self._inline.display = True
        image = frames.frame(cursor.index)
        if self.current is not None and self.current.cone:
            image = crop_cone(image)
        setattr(self._inline, "image", image)  # noqa: B010

    def _update_caption(self, *, loading: bool = False) -> None:
        item = self.current
        text = Text(no_wrap=False)
        if item is not None:
            text.append(f" {item.title}", style="bold")
            frames, cursor = self._frames, self._cursor
            if frames is not None and cursor is not None and frames.animated:
                state = "playing" if cursor.playing else "paused"
                text.append(f"   frame {cursor.index + 1}/{cursor.count} {state}", style=DIM)
            elif loading:
                text.append("   loading", style=DIM)
            if item.url.startswith(("http://", "https://")):  # a recording's address means nothing to a reader
                text.append(f"\n {item.url}", style=DIM)
        self.query_one("#gal-caption", Static).update(text)

    def _update_hint(self) -> None:
        """Tell the footer: the keys that work depend on whether the picture is animated (`check_action`)."""
        if self.current is None:
            self.query_one("#gal-caption", Static).update("")
        refresh = getattr(self.screen, "refresh_status", None)
        if refresh is not None:
            refresh()

    # ---- loops ------------------------------------------------------------------------------------------------

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _restart_timer(self) -> None:
        self._stop_timer()
        frames, cursor = self._frames, self._cursor
        if not self.active or frames is None or cursor is None or not cursor.playing or not self.is_attached:
            self._update_hint()
            return
        self._timer = self.set_interval(frames.interval, self._tick)
        self._update_hint()

    def _tick(self) -> None:
        cursor = self._cursor
        if cursor is None:
            self._stop_timer()
            return
        try:
            cursor.advance()
            self._paint()
        except Exception:
            self._stop_timer()
            log.exception("the loop stopped")
            if not self._failed_toast:
                self._failed_toast = True
                self.eye.notify("The loop stopped after an error. See the log.", severity="error", timeout=6)

    # ---- actions ----------------------------------------------------------------------------------------------

    def check_action(self, action: str, _parameters: tuple[object, ...]) -> bool | None:
        if action in ("step", "toggle_loop"):
            return self._frames is not None and self._frames.animated  # on a still the key goes on to the app
        return True

    def action_step(self, delta: int) -> None:
        if self._cursor is None:
            return
        self._cursor.step(delta)
        self._stop_timer()
        self._paint()

    def action_toggle_loop(self) -> None:
        if self._cursor is None:
            return
        self._cursor.toggle()
        self._restart_timer()
        self._update_caption()

    async def action_open_url(self) -> None:
        item = self.current
        if item is None:
            return
        if not item.url.startswith(("http://", "https://")):
            self.eye.notify("This image is part of the recording, so it has no web address.", timeout=5)
            return
        if not is_noaa_url(item.url):
            self.eye.notify("Not a NOAA link.", severity="warning", timeout=5)
            return
        try:
            outcome = await asyncio.to_thread(open_in_browser, item.url)
        except Exception:
            log.exception("could not open %s", item.url)
            outcome = "none"
        if outcome == "console":
            self.eye.notify(
                "The only browser here runs inside this terminal. Press y to copy the address instead.",
                severity="warning",
                timeout=10,
            )
        elif outcome != "opened":
            self.eye.notify(
                f"No browser could be opened here. Address: {item.url}", severity="warning", timeout=10, markup=False
            )

    def action_copy_url(self) -> None:
        item = self.current
        if item is None:
            return
        try:
            self.eye.copy_to_clipboard(item.url)
        except Exception:
            log.exception("could not copy %s", item.url)
            self.eye.notify(
                f"Could not use the clipboard. Address: {item.url}", severity="warning", timeout=10, markup=False
            )
            return
        self.eye.notify("Copied the address (the terminal must allow clipboard access).", timeout=4)


CONSOLE_BROWSERS = frozenset({"lynx", "w3m", "links", "links2", "elinks", "browsh", "www-browser", "wget", "curl"})


def open_in_browser(url: str) -> str:
    """Open the address in the desktop browser: `opened`, `console` (refused) or `none`. Blocks, so run it in a thread.

    A browser that runs in the terminal (lynx, w3m, links) would take over the screen Textual draws on, so those are
    never started.
    """
    controller = webbrowser.get()
    name = os.path.basename(str(getattr(controller, "name", ""))).lower().removesuffix(".exe")
    if (name.split() or [""])[0] in CONSOLE_BROWSERS:
        return "console"
    return "opened" if controller.open(url) else "none"


def _open_frames(data: bytes) -> Frames:
    """Open the image and decode its first frame, in a worker thread, so the event loop only draws."""
    frames = Frames(data)
    try:
        frames.frame(0)
    except BaseException:
        frames.close()
        raise
    return frames


def _option_text(item: GalleryItem) -> Text:
    mark = "~" if item.loop else " "
    text = Text(no_wrap=True, overflow="ellipsis")
    text.append(f"{mark} {item.title}", style="" if item.viewable else DIM)
    return text
