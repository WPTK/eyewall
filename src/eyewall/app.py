"""The Textual app: starts the poller in a worker, keeps the store, and hands it to the screens.

The app cannot tell a live source from a replay except for one thing: a replay has a virtual clock that nothing moves
unless the app does, so it advances the clock a few times a second (`space` pauses, `<` `>` change the speed) and polls
whatever is due. A live app runs `Poller.run()` and lets the poller sleep.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Any

from rich.text import Text
from textual import events
from textual.app import App
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.screen import ModalScreen, Screen

from eyewall.config import Config, save_config, toggle_watch, watchlist_ids
from eyewall.models.events import Event, Severity
from eyewall.models.graphics import FloaterProduct
from eyewall.models.obs import Parsed, SupplementalReading
from eyewall.net import FetchError
from eyewall.poll import DATUM_COAST, DATUM_GREAT_LAKES, Poller, PollResult
from eyewall.providers.base import ParseError
from eyewall.render.canvas import Mode
from eyewall.render.images import Depth, InlineBackend, load_inline
from eyewall.render.layers import MapOptions
from eyewall.sources import protocol
from eyewall.sources.protocol import DataSource
from eyewall.sources.replay import ReplaySource
from eyewall.state.alerts import AlertEngine
from eyewall.state.store import Store
from eyewall.ui import format as fmt
from eyewall.ui.glyphs import UiGlyphs, glyphs_for
from eyewall.ui.screens.alerts import AlertLogScreen
from eyewall.ui.screens.buoy_detail import BuoyDetailScreen
from eyewall.ui.screens.dashboard import DashboardScreen
from eyewall.ui.screens.detail import StormDetailScreen
from eyewall.ui.screens.graphics import GraphicsScreen
from eyewall.ui.screens.help import HelpScreen
from eyewall.ui.screens.layers import LayerMenu
from eyewall.ui.screens.outlook import OutlookScreen
from eyewall.ui.screens.search import SearchChoice, SearchScreen
from eyewall.ui.screens.settings import SettingsScreen
from eyewall.ui.screens.small import TooSmallScreen, too_small
from eyewall.ui.screens.watchlist import WatchlistScreen
from eyewall.ui.theme import EYEWALL_THEME, THEME_NAME
from eyewall.units import PRESETS, Preset, next_preset

log = logging.getLogger(__name__)

REPLAY_SPEEDS = (60, 300, 1200, 3600)  # virtual seconds per real second
DEFAULT_SPEED = 1
REPLAY_TICK = 0.5  # real seconds between clock advances
TOAST_SECONDS = 8.0
REPLAY_ACTIONS = frozenset({"play_pause", "speed", "step"})


SUPL_TTL = 600.0  # seconds a buoy's supplemental file is reused
FLOATER_TTL = 600.0  # seconds a NESDIS product listing is reused (its stills arrive every 10 to 15 minutes)
IMAGE_MEMORY = 48 * 1024 * 1024  # bytes of downloaded images kept in memory


class EyewallApp(App[None]):
    CSS_PATH = "ui/app.tcss"
    TITLE = "eyewall"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("q", "quit", "Quit", show=False),
        Binding("question_mark", "help", "Help", show=False),
        Binding("g", "graphics", "Graphics", show=False),
        Binding("O", "outlook", "Outlook", show=False),
        Binding("A", "alerts", "Alerts", show=False),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("u", "units", "Units", show=False),
        Binding("slash", "search", "Find station", show=False),
        Binding("w", "watchlist", "Watchlist", show=False),
        Binding("S", "settings", "Settings", show=False),
        Binding("space", "play_pause", "Pause", show=False),
        Binding("less_than_sign", "speed(-1)", "Slower", show=False),
        Binding("greater_than_sign", "speed(1)", "Faster", show=False),
        Binding("left_square_bracket", "step(-1)", "Previous advisory", show=False),
        Binding("right_square_bracket", "step(1)", "Next advisory", show=False),
    ]

    def __init__(
        self,
        config: Config,
        source: DataSource,
        *,
        state_dir: Path | None = None,
        local_tz: tzinfo | None = None,
        autoplay: bool = True,
        closer: Callable[[], Awaitable[None]] | None = None,
        config_path: Path | None = None,
        file_config: Config | None = None,
        config_file_broken: bool = False,
        inline: InlineBackend | None = None,
    ) -> None:
        """`config_path` is where settings and the watchlist are saved; None keeps changes for this run only.
        `file_config` is the config as the file had it, before command-line flags: a flag is never saved unless the
        settings screen changes that value. `config_file_broken` says the file could not be read, so it is copied to
        a `.bak` before the first save replaces it. `inline` is the terminal graphics backend
        `render.images.load_inline` found before the app started, or None for the cell-drawn fallback."""
        super().__init__()
        self.config = config
        self.config_path = config_path
        self._launch_config = config
        self._supl: dict[str, tuple[float, Parsed[SupplementalReading]]] = {}
        self.inline = inline
        self._images: OrderedDict[tuple[str, str], bytes] = OrderedDict()
        self._floaters: dict[tuple[str, str], tuple[float, FloaterProduct | None]] = {}
        self._file_config = file_config
        self._file_broken = config_file_broken
        self.source = source
        self.replay: ReplaySource | None = source if isinstance(source, ReplaySource) else None
        self.local_tz = local_tz
        self.glyphs: UiGlyphs = glyphs_for(config.map.glyph_set)
        self.map_mode = Mode.ASCII if config.map.glyph_set == "ascii" else Mode.BRAILLE
        self.map_options = MapOptions(
            land=config.map.land, borders=config.map.borders, cone=config.map.cone, radii=config.map.radii
        )
        self.units = config.units.preset
        self.store = Store(config)
        self.alert_log: list[Event] = []
        self.results: dict[str, PollResult] = {}
        self.selected: str | None = None
        self.basin_filter: str | None = None
        self.paused = not autoplay
        self.speed_index = DEFAULT_SPEED
        self.first_poll = asyncio.Event()
        self._closer = closer
        self._last_input = time.monotonic()
        self._tick_lock = asyncio.Lock()
        self._reported: set[str] = set()
        self.replay_over = False
        engine = AlertEngine(config.alerts, state_dir)
        self.poller = Poller(
            source,
            self.store,
            engine,
            config.poll,
            clock=self.replay.clock if self.replay else None,
            on_events=self._on_events,
            on_result=self._on_result,
            idle_for=None if self.replay else self._idle_seconds,
        )

    # ---- state the screens read -------------------------------------------------------------------------------

    @property
    def preset(self) -> Preset:
        return PRESETS[self.units]

    def now(self) -> datetime:
        return self.source.now()

    @property
    def basin_view(self) -> tuple[str, ...]:
        enabled = self.config.basins.enabled
        return (self.basin_filter,) if self.basin_filter in enabled else enabled

    def status_text(self, width: int, screen: Screen[Any]) -> Text:
        feeds = [fmt.FeedStatus(f, self.poller.freshness(f), self.poller.active(f)) for f in protocol.FEEDS]
        replay = None
        if self.replay is not None:
            adv = next((str(s.advisories.adv_num) for s in self.store.storms.values() if s.advisories.adv_num), None)
            replay = fmt.ReplayStatus(
                self.paused, REPLAY_SPEEDS[self.speed_index], self.replay.now(), adv, self.replay_over
            )
        text = fmt.status_bar(
            feeds,
            next_poll=self.poller.seconds_until_next(),
            alert_count=len(self.alert_log),
            replay=replay,
            away=self.poller.away,
            width=width,
            g=self.glyphs,
        )
        if width >= 70:  # `? help` keeps its place, then the keys; the status gives way
            text = fmt.footer_row(text, self.footer_keys(screen), width)
        return text

    def footer_keys(self, screen: Screen[Any]) -> list[tuple[str, str]]:
        """The keys that work where the focus is on `screen`: Textual's own active bindings, nearest widget first,
        filtered to the ones marked `show` and not disabled by their widget's `check_action`."""
        keys: dict[str, tuple[str, str]] = {}
        for active in screen.active_bindings.values():
            binding = active.binding
            if binding.show and active.enabled and binding.description and binding.action not in keys:
                keys[binding.action] = (binding.key_display or fmt.key_name(binding.key), binding.description)
        return list(keys.values())

    def on_descendant_focus(self) -> None:
        self._for_screens("refresh_status")

    def on_descendant_blur(self) -> None:
        self._for_screens("refresh_status")  # also when the focus clears, which fires no focus event

    def on_tabbed_content_tab_activated(self) -> None:
        self._for_screens("refresh_status")

    def _idle_seconds(self) -> float:
        return time.monotonic() - self._last_input

    # ---- lifecycle --------------------------------------------------------------------------------------------

    def get_default_screen(self) -> Screen[None]:
        return DashboardScreen()

    def on_mount(self) -> None:
        self.register_theme(EYEWALL_THEME)
        self.theme = THEME_NAME
        self.set_interval(1.0, self._pulse)
        if self.replay is None and self.config_path is not None and not self.config_path.exists():
            self.notify(f"Settings are saved to {self.config_path}", timeout=6)
        if self.replay is not None:
            times = self.replay.advisory_times()
            if times and times[0] > self.replay.now():
                self.replay.step_advisory(1)  # open on the first advisory instead of the empty hours before it
            self.set_interval(REPLAY_TICK, self._replay_tick)
        self.run_worker(self._startup(), name="poller", exit_on_error=True)

    async def _startup(self) -> None:
        if self.replay is not None:
            await self._tick()
        else:
            await self.poller.run()

    async def on_unmount(self) -> None:
        self.poller.stop()
        if self._closer is not None:
            await self._closer()

    def on_resize(self, event: events.Resize) -> None:
        if too_small(*event.size) and not isinstance(self.screen, TooSmallScreen):
            self.push_screen(TooSmallScreen())

    async def on_event(self, event: events.Event) -> None:
        if isinstance(event, events.Key | events.MouseEvent):
            self._last_input = time.monotonic()
        await super().on_event(event)

    async def _tick(self) -> None:
        async with self._tick_lock:
            await self.poller.tick()

    async def _replay_tick(self) -> None:
        if self.replay is None or self.paused or self._tick_lock.locked():
            return
        async with self._tick_lock:
            end = self.replay.manifest.end
            remaining = (end - self.replay.now()).total_seconds()
            if remaining <= 0:
                self._finish_replay()
                return
            self.replay.clock.advance(min(REPLAY_SPEEDS[self.speed_index] * REPLAY_TICK, remaining))
            await self.poller.tick()
            if self.replay.now() >= end:
                self._finish_replay()

    def _finish_replay(self) -> None:
        """The recording has run out: stop the clock and say so."""
        self.paused = True
        if not self.replay_over:
            self.replay_over = True
            self.notify("The replay is over; use [ to step back through the advisories.", timeout=8)
        self._for_screens("refresh_status")

    def _pulse(self) -> None:
        """Once a second: notice the user coming back from away mode and let the clocks on screen tick."""
        if self.poller.observe_presence():
            self.notify("Welcome back; refreshing every feed.", timeout=4)
        self._for_screens("refresh_status")

    # ---- results from the poller ------------------------------------------------------------------------------

    def _on_events(self, events_: list[Event]) -> None:
        try:
            self._show_events(events_)
        except Exception:
            self._report_failure("the alert toasts")

    def _show_events(self, events_: list[Event]) -> None:
        for event in events_:
            self.alert_log.insert(0, event)
            self.notify(
                event.message,
                title=fmt.event_title(event),
                severity="warning" if event.severity is Severity.WARNING else "information",
                timeout=TOAST_SECONDS,
            )
        if events_ and self.config.alerts.bell:
            self.bell()

    def _on_result(self, result: PollResult) -> None:
        try:
            self._store_result(result)
        except Exception:
            self._report_failure("the poll result handler")

    def _store_result(self, result: PollResult) -> None:
        self.results[result.feed] = result
        self._for_screens("refresh_data")
        self._for_screens("refresh_status")
        if result.feed == protocol.STORMS:
            self.first_poll.set()

    def _report_failure(self, where: str) -> None:
        """Log an exception raised by a screen or a listener, and tell the user once per place."""
        log.exception("%s failed", where)
        if where not in self._reported:
            self._reported.add(where)
            self.notify(f"{where} failed; data keeps polling. See the log.", severity="error", timeout=TOAST_SECONDS)

    def _for_screens(self, method: str) -> None:
        for screen in list(self.screen_stack):
            action = getattr(screen, method, None)
            if action is not None and screen.is_attached:
                try:
                    action()
                except NoMatches:  # a screen still being built or torn down
                    continue
                except Exception:  # a screen bug must not stop the polling; say so and carry on
                    self._report_failure(f"{type(screen).__name__}.{method}")

    # ---- screens ----------------------------------------------------------------------------------------------

    def _modal_open(self) -> bool:
        return isinstance(self.screen, ModalScreen)

    def open_detail(self, storm_id: str | None, tab: str | None = None) -> None:
        if storm_id is not None and not isinstance(self.screen, StormDetailScreen):
            self.push_screen(StormDetailScreen(storm_id, tab))

    def open_graphics(self, storm_id: str | None) -> None:
        screen = self.screen
        if storm_id is None or storm_id not in self.store.storms:
            self.notify("Select a storm first: graphics are per storm.", timeout=4)
        elif not isinstance(screen, ModalScreen | GraphicsScreen):
            self.push_screen(GraphicsScreen(storm_id))

    def open_buoy(self, station_id: str) -> None:
        screen = self.screen
        if isinstance(screen, ModalScreen) or (
            isinstance(screen, BuoyDetailScreen) and screen.station_id == station_id.upper()
        ):
            return
        self.push_screen(BuoyDetailScreen(station_id))

    def open_layers(self) -> None:
        def apply(options: MapOptions | None) -> None:
            if options is not None:
                self.map_options = options
                for screen in self.screen_stack:
                    view = getattr(screen, "map_view", None)
                    if view is not None:
                        view.set_options(options)

        self.push_screen(LayerMenu(self.map_options), apply)

    def action_graphics(self) -> None:
        screen = self.screen
        storm_id = getattr(screen, "storm_id", None) if isinstance(screen, StormDetailScreen) else self.selected
        self.open_graphics(storm_id)

    def action_help(self) -> None:
        if not self._modal_open():
            self.push_screen(HelpScreen())

    def action_outlook(self) -> None:
        if not self._modal_open() and not isinstance(self.screen, OutlookScreen):
            self.push_screen(OutlookScreen())

    def action_alerts(self) -> None:
        if not self._modal_open() and not isinstance(self.screen, AlertLogScreen):
            self.push_screen(AlertLogScreen())

    async def action_refresh(self) -> None:
        self.poller.refresh()
        if self.replay is not None:
            await self._tick()
        self.notify("Refreshing every feed.", timeout=3)

    def action_units(self) -> None:
        self.units = next_preset(self.units)
        self._for_screens("refresh_data")
        self.notify(f"Units: {self.units}", timeout=3)

    def action_watchlist(self) -> None:
        if not self._modal_open() and not isinstance(self.screen, WatchlistScreen):
            self.push_screen(WatchlistScreen())

    def action_search(self) -> None:
        if self._modal_open():
            return

        def picked(choice: SearchChoice | None) -> None:
            if choice is None:
                return
            if choice.pin or choice.kind == "coops":  # a gauge has no page of its own, so opening it pins it
                self.watch_in_background(choice.kind, choice.id, True)
            else:
                self.open_buoy(choice.id)

        self.push_screen(SearchScreen(), picked)

    def action_settings(self) -> None:
        if self._modal_open():
            return

        def saved(config: Config | None) -> None:
            if config is not None:
                self.apply_config(config)

        self.push_screen(SettingsScreen(self.config, self.units), saved)

    # ---- settings and the watchlist ---------------------------------------------------------------------------

    def apply_config(self, new: Config, *, persist: bool = True) -> bool:
        """Make a changed config take effect everywhere and save it. False when the file could not be written."""
        old = self.config
        self.config = new
        self.store.config = new
        self.poller.config = new.poll
        self.poller.engine.rules = new.alerts
        if new.units != old.units:
            self.units = new.units.preset
        if new.map != old.map:
            self.glyphs = glyphs_for(new.map.glyph_set)
            self.map_mode = Mode.ASCII if new.map.glyph_set == "ascii" else Mode.BRAILLE
            self.map_options = replace(
                self.map_options, land=new.map.land, borders=new.map.borders, cone=new.map.cone, radii=new.map.radii
            )
            for screen in self.screen_stack:
                view = getattr(screen, "map_view", None)
                if view is not None:
                    view.set_mode(self.map_mode)
                    view.set_options(self.map_options)
        if new.basins != old.basins and self.basin_filter not in new.basins.enabled:
            self.basin_filter = None
        due: set[str] = set()
        if new.watchlist != old.watchlist:
            due.update((protocol.BUOYS, protocol.TIDES))
        if new.basins != old.basins:
            due.update((protocol.STORMS, protocol.OUTLOOK, protocol.ALERTS))
        if new.nearby != old.nearby:
            due.update((protocol.BUOYS, protocol.TIDES))
        due.update(name for name in protocol.FEEDS if getattr(new.poll, name, None) != getattr(old.poll, name, None))
        if due:
            self.poller.refresh_feeds(*sorted(due))
        saved = True
        if persist and self.config_path is not None:
            saved = self._save(new)
        self._for_screens("refresh_data")
        self._for_screens("refresh_status")
        return saved

    def _for_save(self, new: Config) -> Config:
        """The config to write: `new` with the command-line flags taken back out where the user did not change them."""
        base, launch, out = self._file_config, self._launch_config, new
        if base is None:
            return out
        if new.basins == launch.basins:
            out = replace(out, basins=base.basins)
        if new.map.glyph_set == launch.map.glyph_set:
            out = replace(out, map=replace(out.map, glyph_set=base.map.glyph_set))
        return out

    def _save(self, new: Config) -> bool:
        path = self.config_path
        if path is None:
            return True
        try:
            if self._file_broken and path.exists():
                backup = path.with_name(path.name + ".bak")
                for n in range(1, 100):  # never overwrite an earlier backup
                    if not backup.exists():
                        break
                    backup = path.with_name(f"{path.name}.bak{n}")
                shutil.copy2(path, backup)
                self.notify(f"{path.name} could not be read; the original is kept as {backup.name}.", timeout=8)
            save_config(self._for_save(new), path)
        except OSError as exc:
            self.notify(f"Could not save {path}: {exc.strerror or exc}", severity="error", timeout=8)
            return False
        self._file_broken = False
        return True

    async def fetch_series(self, station_id: str) -> None:
        """Fetch one buoy's series now, for a page that was just opened; the rest of the buoys feed is left alone."""
        try:
            self.store.apply_series(await self.source.ndbc_series(station_id.upper()))
        except (FetchError, ParseError):
            return
        self._for_screens("refresh_data")

    async def fetch_tide(self, station_id: str) -> None:
        """Fetch one tide gauge now (it was just pinned), not every gauge."""
        gauge = next((g for g in self.store.tide_stations if g.id.upper() == station_id.upper()), None)
        if gauge is None:
            return
        datum = DATUM_GREAT_LAKES if gauge.great_lakes else DATUM_COAST
        try:
            self.store.apply_tide_series(await self.source.coops_series(gauge, datum))
        except (FetchError, ParseError) as exc:
            self.store.apply_tide_error(gauge.id, str(exc))
        self._for_screens("refresh_data")

    async def supplemental(self, station_id: str) -> Parsed[SupplementalReading]:
        """A buoy's `.supl` file, remembered for SUPL_TTL seconds so reopening a page does not fetch it again."""
        station_id = station_id.upper()
        kept = self._supl.get(station_id)
        if kept is not None and time.monotonic() - kept[0] < SUPL_TTL:
            return kept[1]
        result = await self.source.ndbc_supplemental(station_id)
        self._supl[station_id] = (time.monotonic(), result)
        return result

    @property
    def color_depth(self) -> Depth:
        """How many colors the terminal shows, for the picture fallback."""
        return Depth.from_rich(self.console.color_system)

    async def load_image(self, url: str, version: str = "") -> bytes:
        """The bytes of a graphic, kept in memory (newest 48 MB) under the address and the version that was current.

        `version` is the advisory number or the satellite time: a new one fetches again (the disk cache sends the
        validators, so an unchanged file costs a 304), the same one never touches the network.
        """
        key = (url, version)
        if key in self._images:
            self._images.move_to_end(key)
            return self._images[key]
        data = await self.source.image(url)
        self._images = OrderedDict((k, v) for k, v in self._images.items() if k[0] != url)
        self._images[key] = data
        while len(self._images) > 1 and sum(len(v) for v in self._images.values()) > IMAGE_MEMORY:
            self._images.popitem(last=False)
        return data

    def floaters_for(self, storm_id: str) -> dict[str, FloaterProduct | None]:
        """The satellite products the gallery has already asked NESDIS for, by product code."""
        return {code: found for (sid, code), (_, found) in self._floaters.items() if sid == storm_id}

    async def floater(self, storm_id: str, code: str) -> bool:
        """List one NESDIS product for a storm (remembered for 10 minutes). True when the answer changed the gallery."""
        key = (storm_id, code)
        kept = self._floaters.get(key)
        if kept is not None and time.monotonic() - kept[0] < FLOATER_TTL:
            return False
        state = self.store.storms.get(storm_id)
        if state is None:
            return False
        try:
            found = await self.source.satellite_product(state.storm, code)
        except (FetchError, ParseError):
            found = kept[1] if kept is not None else None
        self._floaters[key] = (time.monotonic(), found)
        return found is not None and (kept is None or kept[1] != found)

    async def toggle_watch(self, kind: str, station_id: str) -> None:
        """Pin a station to the watchlist, or unpin it when it is there already."""
        station_id = station_id.upper()
        updated, watched = toggle_watch(self.config, kind, station_id)
        if watched and station_id not in watchlist_ids(updated, kind):
            self.notify("The watchlist is full.", severity="warning", timeout=4)
            return
        self.apply_config(updated)
        verb = "Pinned" if watched else "Removed"
        self.notify(f"{verb} {station_id} {'to' if watched else 'from'} the watchlist.", timeout=3)
        if not watched:
            return
        if kind == "coops":
            await self.fetch_tide(station_id)
        elif not self.store.latest:  # the buoys feed was idle, so no observation has been read yet
            self.poller.refresh_feeds(protocol.BUOYS)

    def watch_in_background(self, kind: str, station_id: str, wanted: bool) -> None:
        """Pin or unpin from a key press. A failure is logged and shown as a toast, never an app crash."""

        async def work() -> None:
            try:
                await self.set_watch(kind, station_id, wanted)
            except Exception as exc:
                log.exception("could not %s %s", "pin" if wanted else "unpin", station_id)
                self.notify(f"Could not change the watchlist: {exc}", severity="error", timeout=8)

        self.run_worker(work(), exclusive=False, exit_on_error=False)

    async def set_watch(self, kind: str, station_id: str, wanted: bool) -> None:
        if (station_id.upper() in watchlist_ids(self.config, kind)) != wanted:
            await self.toggle_watch(kind, station_id)

    async def ensure_catalogs(self) -> bool:
        """Load the buoy and tide gauge catalogs for the search when the poller has not (a quiet day with no
        watchlist). Returns True when either could not be fetched."""
        failed = False
        try:
            if not self.store.stations:
                self.store.apply_stations(await self.source.ndbc_stations())
            if not self.store.tide_stations:
                self.store.apply_tide_stations(await self.source.coops_stations())
        except (FetchError, ParseError):
            failed = True
        return failed

    # ---- replay transport -------------------------------------------------------------------------------------

    def check_action(self, action: str, _parameters: tuple[object, ...]) -> bool | None:
        return not (action in REPLAY_ACTIONS and self.replay is None)

    def action_play_pause(self) -> None:
        self.paused = not self.paused
        self._for_screens("refresh_status")

    def action_speed(self, step: int) -> None:
        self.speed_index = max(0, min(len(REPLAY_SPEEDS) - 1, self.speed_index + step))
        self._for_screens("refresh_status")

    async def action_step(self, direction: int) -> None:
        if self.replay is None:
            return
        async with self._tick_lock:  # the clock move and the refresh must not interleave with a replay tick
            if self.replay.step_advisory(direction) is None:
                self.notify(
                    "No later advisory in this replay." if direction > 0 else "This is the first advisory.", timeout=3
                )
                return
            self.replay_over = False
            self.poller.refresh()
            await self.poller.tick()


def run_app(
    config: Config,
    source: DataSource,
    *,
    state_dir: Path | None,
    closer: Callable[[], Awaitable[None]] | None = None,
    config_path: Path | None = None,
    file_config: Config | None = None,
    config_file_broken: bool = False,
) -> None:
    inline = None if config.map.glyph_set == "ascii" else load_inline(config.graphics.inline)
    EyewallApp(
        config,
        source,
        inline=inline,
        state_dir=state_dir,
        closer=closer,
        config_path=config_path,
        file_config=file_config,
        config_file_broken=config_file_broken,
    ).run()
