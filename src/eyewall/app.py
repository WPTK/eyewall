"""The Textual app: starts the poller in a worker, keeps the store, and hands it to the screens.

The app cannot tell a live source from a replay except for one thing: a replay has a virtual clock that nothing moves
unless the app does, so it advances the clock a few times a second (`space` pauses, `<` `>` change the speed) and polls
whatever is due. A live app runs `Poller.run()` and lets the poller sleep.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime, tzinfo
from pathlib import Path

from textual import events
from textual.app import App
from textual.command import CommandPalette
from textual.css.query import NoMatches
from textual.screen import ModalScreen, Screen

from eyewall.config import Config, save_config, toggle_watch, watchlist_ids
from eyewall.models.events import Event, Severity
from eyewall.models.graphics import FloaterProduct
from eyewall.models.obs import Parsed, SupplementalReading
from eyewall.models.storm import Classification
from eyewall.net import FetchError
from eyewall.poll import DATUM_COAST, DATUM_GREAT_LAKES, FreshnessState, Poller, PollResult
from eyewall.providers.base import ParseError
from eyewall.render.canvas import Mode
from eyewall.render.images import Depth, InlineBackend, inline_wanted, load_inline
from eyewall.render.layers import MapOptions
from eyewall.sources import protocol
from eyewall.sources.bundle import DEMO, BundleError, resolve_bundle
from eyewall.sources.protocol import DataSource
from eyewall.sources.replay import ReplaySource
from eyewall.state.alerts import AlertEngine
from eyewall.state.store import Store, StormState
from eyewall.ui import format as fmt
from eyewall.ui import nav
from eyewall.ui.chrome import ChromeScreen, FeedStatus, Health, ReplayStatus, health
from eyewall.ui.glyphs import UiGlyphs, glyphs_for
from eyewall.ui.screens.alerts import AlertLogScreen
from eyewall.ui.screens.buoys import BuoysScreen
from eyewall.ui.screens.feeds import FeedsScreen
from eyewall.ui.screens.graphics import GraphicsScreen
from eyewall.ui.screens.help import HelpScreen
from eyewall.ui.screens.layers import LayerMenu
from eyewall.ui.screens.main import MainScreen
from eyewall.ui.screens.nhc_text import NhcTextScreen
from eyewall.ui.screens.settings import SettingsScreen
from eyewall.ui.screens.small import TooSmallScreen, too_small
from eyewall.ui.screens.station import StationScreen
from eyewall.ui.screens.storm import StormScreen
from eyewall.ui.theme import EYEWALL_THEME, THEME_NAME
from eyewall.ui.widgets.map_view import MapView
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


class EyewallApp(App[bool]):
    CSS_PATH = "ui/app.tcss"
    TITLE = "eyewall"
    ENABLE_COMMAND_PALETTE = True
    COMMANDS = {nav.EyewallCommands}  # the menu lists eyewall's own actions, not Textual's theme and quit commands

    BINDINGS = nav.bindings("app", "replay")

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
        self._supl: dict[str, tuple[float, Parsed[SupplementalReading] | FetchError | ParseError]] = {}
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
        self.catalogs_task: asyncio.Future[bool] | None = None  # the menu's one fetch of the station catalogs
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

    def feed_statuses(self) -> list[FeedStatus]:
        return [FeedStatus(f, self.poller.freshness(f), self.poller.active(f)) for f in protocol.FEEDS]

    def replay_status(self) -> ReplayStatus | None:
        if self.replay is None:
            return None
        adv = next((str(s.advisories.adv_num) for s in self.store.storms.values() if s.advisories.adv_num), None)
        return ReplayStatus(self.paused, REPLAY_SPEEDS[self.speed_index], self.replay.now(), adv, self.replay_over)

    def health(self) -> Health:
        """What the top bar's health slot says now."""
        return health(self.feed_statuses(), self.replay_status(), self.glyphs)

    def top_bar_extras(self) -> list[tuple[str, str | None]]:
        """What the top bar shows beside the breadcrumb when there is room, most important first: the alert
        count, the idle marker, the replay time."""
        extras: list[tuple[str, str | None]] = []
        if self.alert_log:
            count = len(self.alert_log)
            extras.append((f"{count} alert" + ("" if count == 1 else "s"), "app:alerts"))
        if self.poller.away:
            extras.append(("idle", None))
        replay = self.replay_status()
        if replay is not None:  # the clock is the first to go when the bar is tight
            when = f"{replay.moment:%a %d %b %H:%MZ}" + (f" adv {replay.adv}" if replay.adv else "")
            extras.append((when, None))
        return extras

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
        return MainScreen()

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
        self.call_after_refresh(self._for_screens, "refresh_status")  # the one place every bar follows a resize

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

    def _can_go_back(self) -> bool:
        screen = self.screen
        return isinstance(screen, ChromeScreen) and screen.can_go_back()

    async def action_back(self) -> None:
        """Esc: one step back out of the screen, a full-screen map or a mark. A dialog closes itself."""
        if self._can_go_back():
            self.screen.action_back()  # type: ignore[attr-defined]

    def action_quit_top(self) -> None:
        """`q`: quit, but only on the first screen, where Esc has nothing to go back to."""
        if self.check_action(nav.QUIT, ()):
            self.exit()

    async def action_crumb(self, index: int) -> None:
        """A breadcrumb was clicked: go back to that screen."""
        chrome = [s for s in self.screen_stack if isinstance(s, ChromeScreen)]
        if not 0 <= index < len(chrome):
            return
        target = chrome[index]
        while self.screen is not target and len(self.screen_stack) > 1:
            await self.pop_screen()

    async def action_map(self) -> None:
        """`m` from another screen: back to the first screen with its map showing."""
        if self._modal_open():
            return
        while len(self.screen_stack) > 1:
            await self.pop_screen()
        root = self.screen
        if isinstance(root, MainScreen):
            root.show_map()

    def action_feeds(self) -> None:
        if not self._modal_open():
            self.push_screen(FeedsScreen())

    def storm_states(self) -> tuple[StormState, ...]:
        """The storms of the basins in view, strongest first (a potential cyclone after the named storms)."""
        shown = [
            s
            for s in self.store.storms.values()
            if s.storm.basin is not None and s.storm.basin.value in self.basin_view
        ]
        shown.sort(key=lambda s: (s.storm.classification is Classification.PTC, -(s.storm.intensity_kt or 0)))
        return tuple(shown)

    def _can_open(self, kind: type[Screen[None]]) -> bool:
        """False under a dialog, and when the top screen is already this kind (a repeated key opens nothing twice)."""
        return not isinstance(self.screen, ModalScreen | kind)

    def open_storm(self, storm_id: str | None) -> None:
        if storm_id is not None and storm_id in self.store.storms and self._can_open(StormScreen):
            self.selected = storm_id
            self.push_screen(StormScreen(storm_id))

    def open_text(self, storm_id: str | None, tab: str | None = None) -> None:
        """The NHC text: a storm's products, or the outlook alone when there is no storm."""
        if self._can_open(NhcTextScreen):
            self.push_screen(NhcTextScreen(storm_id if storm_id in self.store.storms else None, tab))

    def open_buoys(self, storm_id: str | None, tab: str | None = None) -> None:
        """The stations near a storm and the ones you follow; just the latter when there is no storm."""
        if self._can_open(BuoysScreen):
            self.push_screen(BuoysScreen(storm_id if storm_id in self.store.storms else None, tab))

    def open_station(self, kind: str, station_id: str) -> None:
        screen = self.screen
        if isinstance(screen, ModalScreen) or (
            isinstance(screen, StationScreen) and screen.station_id == station_id.upper() and screen.kind == kind
        ):
            return
        self.push_screen(StationScreen(kind, station_id))

    async def show_on_map(self, lat: float, lon: float, label: str) -> None:
        """`m` on a station: back to the map, centred on it."""
        while len(self.screen_stack) > 1:
            await self.pop_screen()
        root = self.screen
        if isinstance(root, MainScreen):
            root.show_map()
            root.map_view.center_on((lat, lon))
            self.notify(f"{label} is at the centre of the map.", timeout=3)

    def open_graphics(self, storm_id: str | None) -> None:
        screen = self.screen
        if storm_id is None or storm_id not in self.store.storms:
            self.notify("Select a storm first: graphics are per storm.", timeout=4)
        elif not isinstance(screen, ModalScreen | GraphicsScreen):
            self.push_screen(GraphicsScreen(storm_id))

    def on_map_view_mark_opened(self, message: MapView.MarkOpened) -> None:
        """A mark on the map was opened: a storm opens its page, a buoy or a tide gauge its station page."""
        message.stop()
        mark = message.mark
        if mark.kind == "storm":
            self.open_storm(mark.id)
        elif mark.kind == "buoy":
            self.open_station("ndbc", mark.id)
        else:
            self.open_station("coops", mark.id)

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
        storm_id = getattr(screen, "storm_id", None) if isinstance(screen, StormScreen) else self.selected
        self.open_graphics(storm_id)

    def action_help(self) -> None:
        if not self._modal_open():
            self.push_screen(HelpScreen())

    def action_alerts(self) -> None:
        if not self._modal_open() and not isinstance(self.screen, AlertLogScreen):
            self.push_screen(AlertLogScreen())

    async def action_refresh(self) -> None:
        self.poller.refresh(throttled=self.replay is None)  # NOAA is asked at most once per gap; a replay asks nobody
        if self.replay is not None:
            await self._tick()
        self.notify("Refreshing every feed.", timeout=3)

    def replay_available(self) -> bool:
        """True when `R` can start the bundled replay: this is live data, and it has nothing to show."""
        if self.replay is not None or not self.store.storms_loaded or self.store.storms:
            return False
        # A failed or stale storm feed says nothing about whether there are storms: no offer on "no storms" then.
        return self.poller.freshness(protocol.STORMS).state not in (FreshnessState.ERROR, FreshnessState.STALE)

    def action_start_replay(self) -> None:
        """End this app with a request for the replay; `run_app` starts it, so the live poller is closed first."""
        if self.replay_available():
            self.exit(True)

    def action_units(self) -> None:
        self.units = next_preset(self.units)
        self._for_screens("refresh_data")
        self.notify(f"Units: {self.units}", timeout=3)

    def action_search(self) -> None:
        """`/`: the menu, with only buoys and tide gauges to find."""
        if self._modal_open() or CommandPalette.is_open(self):  # type: ignore[arg-type]
            return
        self.push_screen(
            CommandPalette(
                providers=[nav.StationCommands], placeholder="Find a buoy or tide gauge by name or number..."
            )
        )

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
        """A buoy's `.supl` file, remembered for SUPL_TTL seconds (a failure too, so a dead file is not asked for on
        every poll). The one place the lifetime is decided; callers may ask as often as they like."""
        station_id = station_id.upper()
        kept = self._supl.get(station_id)
        if kept is not None and time.monotonic() - kept[0] < SUPL_TTL:
            if isinstance(kept[1], (FetchError, ParseError)):
                raise kept[1]
            return kept[1]
        try:
            result = await self.source.ndbc_supplemental(station_id)
        except (FetchError, ParseError) as exc:
            self._supl[station_id] = (time.monotonic(), exc)
            raise
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
        """Follow a station, or stop following it when it is followed already."""
        station_id = station_id.upper()
        updated, watched = toggle_watch(self.config, kind, station_id)
        if watched and station_id not in watchlist_ids(updated, kind):
            self.notify(
                "You follow as many stations as can be kept. Stop following one first.", severity="warning", timeout=4
            )
            return
        self.apply_config(updated)
        self.notify(f"Following {station_id}." if watched else f"Stopped following {station_id}.", timeout=3)
        if not watched:
            return
        if kind == "coops":
            await self.fetch_tide(station_id)
        elif not self.store.latest:  # the buoys feed was idle, so no observation has been read yet
            self.poller.refresh_feeds(protocol.BUOYS)

    def watch_in_background(self, kind: str, station_id: str, wanted: bool) -> None:
        """Follow or unfollow from a key press. A failure is logged and shown as a toast, never an app crash."""

        async def work() -> None:
            try:
                await self.set_watch(kind, station_id, wanted)
            except Exception as exc:
                log.exception("could not %s %s", "follow" if wanted else "unfollow", station_id)
                self.notify(f"Could not change the stations you follow: {exc}", severity="error", timeout=8)

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
        if action in REPLAY_ACTIONS and self.replay is None:
            return False
        if action == "start_replay":
            return self.replay_available()
        if action == nav.BACK:
            return self._can_go_back()
        if action == nav.QUIT:
            if isinstance(self.screen, TooSmallScreen):
                return True  # nothing else works there, so q must
            # The first screen only, and not inside its full-screen map, where Esc is the way out.
            return len(self.screen_stack) == 1 and not self._can_go_back()
        return True

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
    inline = (
        load_inline(config.graphics.inline) if inline_wanted(config.graphics.inline, config.map.glyph_set) else None
    )
    wants_replay = EyewallApp(
        config,
        source,
        inline=inline,
        state_dir=state_dir,
        closer=closer,
        config_path=config_path,
        file_config=file_config,
        config_file_broken=config_file_broken,
    ).run()
    if wants_replay:  # `R` on a quiet day: the live app has closed its feeds, now the recording gets the terminal
        try:
            demo = ReplaySource(resolve_bundle(DEMO))
        except BundleError as exc:
            print(f"eyewall: {exc}", file=sys.stderr)
            return
        EyewallApp(
            config,
            demo,
            inline=inline,
            state_dir=None,  # a replay never reads or writes the real seen set
            config_path=config_path,
            file_config=file_config,
            config_file_broken=config_file_broken,
        ).run()
