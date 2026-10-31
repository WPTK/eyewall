"""The Textual app: starts the poller in a worker, keeps the store, and hands it to the screens.

The app cannot tell a live source from a replay except for one thing: a replay has a virtual clock that nothing moves
unless the app does, so it advances the clock a few times a second (`space` pauses, `<` `>` change the speed) and polls
whatever is due. A live app runs `Poller.run()` and lets the poller sleep.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, tzinfo
from pathlib import Path

from rich.text import Text
from textual import events
from textual.app import App
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.screen import ModalScreen, Screen

from eyewall.config import Config
from eyewall.models.events import Event, Severity
from eyewall.poll import Poller, PollResult
from eyewall.render.canvas import Mode
from eyewall.render.layers import MapOptions
from eyewall.sources import protocol
from eyewall.sources.protocol import DataSource
from eyewall.sources.replay import ReplaySource
from eyewall.state.alerts import AlertEngine
from eyewall.state.store import Store
from eyewall.ui import format as fmt
from eyewall.ui.glyphs import UiGlyphs, glyphs_for
from eyewall.ui.screens.alerts import AlertLogScreen
from eyewall.ui.screens.dashboard import DashboardScreen
from eyewall.ui.screens.detail import StormDetailScreen
from eyewall.ui.screens.help import HelpScreen
from eyewall.ui.screens.layers import LayerMenu
from eyewall.ui.screens.outlook import OutlookScreen
from eyewall.ui.theme import EYEWALL_THEME, THEME_NAME
from eyewall.units import PRESETS, Preset, next_preset

log = logging.getLogger(__name__)

REPLAY_SPEEDS = (60, 300, 1200, 3600)  # virtual seconds per real second
DEFAULT_SPEED = 1
REPLAY_TICK = 0.5  # real seconds between clock advances
TOAST_SECONDS = 8.0
REPLAY_ACTIONS = frozenset({"play_pause", "speed", "step"})


class EyewallApp(App[None]):
    CSS_PATH = "ui/app.tcss"
    TITLE = "eyewall"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help"),
        Binding("O", "outlook", "Outlook"),
        Binding("A", "alerts", "Alerts"),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("u", "units", "Units", show=False),
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
    ) -> None:
        super().__init__()
        self.config = config
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

    def status_text(self, width: int) -> Text:
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
        if width >= 70:
            text.append("  ? help", style="#7d8a99")
        return text

    def _idle_seconds(self) -> float:
        return time.monotonic() - self._last_input

    # ---- lifecycle --------------------------------------------------------------------------------------------

    def get_default_screen(self) -> Screen[None]:
        return DashboardScreen()

    def on_mount(self) -> None:
        self.register_theme(EYEWALL_THEME)
        self.theme = THEME_NAME
        self.set_interval(1.0, self._pulse)
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

    def open_detail(self, storm_id: str | None) -> None:
        if storm_id is not None and not isinstance(self.screen, StormDetailScreen):
            self.push_screen(StormDetailScreen(storm_id))

    def open_layers(self) -> None:
        def apply(options: MapOptions | None) -> None:
            if options is not None:
                self.map_options = options
                for screen in self.screen_stack:
                    view = getattr(screen, "map_view", None)
                    if view is not None:
                        view.set_options(options)

        self.push_screen(LayerMenu(self.map_options), apply)

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
) -> None:
    EyewallApp(config, source, state_dir=state_dir, closer=closer).run()
