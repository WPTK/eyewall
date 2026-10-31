"""The buoy detail screen: sparklines, braille charts of pressure, wind with gust and wave height, the latest
observation and the interval extremes.

The series comes from the poller (the 5 day file, which already covers 72 hours); the `.supl` file with the true
lowest pressure and peak wind inside each interval is fetched once, on demand, when the screen opens.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.screen import Screen
from textual.widgets import Sparkline, Static

from eyewall.models.obs import Parsed, SupplementalReading
from eyewall.net import FetchError
from eyewall.providers.base import ParseError
from eyewall.ui import stations as st
from eyewall.ui.theme import DIM
from eyewall.ui.widgets.chart_view import ChartView
from eyewall.units import LABELS

if TYPE_CHECKING:
    from eyewall.app import EyewallApp

NARROW_BELOW = 110
SPARK_FIELDS = (
    ("pressure", "Pressure", "pressure_hpa", st.PRESSURE_COLOR),
    ("wind", "Wind", "wind_speed_mps", st.WIND_COLOR),
    ("wave", "Wave", "wave_height_m", st.WAVE_COLOR),
)


class BuoyDetailScreen(Screen[None]):
    BINDINGS = [
        Binding("escape,backspace", "back", "Back"),
        Binding("h", "range", "24/48/72 h"),
        Binding("p", "pin", "Pin"),
        Binding("i", "toggle_info", "Info", show=False),
    ]

    def __init__(self, station_id: str) -> None:
        super().__init__()
        self.station_id = station_id.upper()
        self.range_index = 0
        self.supl: Parsed[SupplementalReading] | None = None
        self.supl_note: str | None = "Loading the supplemental file..."
        self._show_info = False

    @property
    def eye(self) -> EyewallApp:
        return self.app  # type: ignore[return-value]

    @property
    def hours(self) -> int:
        return st.RANGES_H[self.range_index]

    def compose(self) -> ComposeResult:
        yield Static("", id="buoy-title")
        with Horizontal(id="buoy-sparks"):
            for key, title, _field, _color in SPARK_FIELDS:
                with Vertical(classes="spark"):
                    yield Static(title, id=f"spark-{key}-label", classes="spark-label")
                    yield Sparkline([], id=f"spark-{key}", summary_function=max)
        with Horizontal(id="buoy-body"):
            with Vertical(id="buoy-charts"):
                yield ChartView(mode=self.eye.map_mode, id="chart-pressure")
                yield ChartView(mode=self.eye.map_mode, id="chart-wind")
                yield ChartView(mode=self.eye.map_mode, id="chart-wave")
            with VerticalScroll(id="buoy-info"):
                yield Static("", id="buoy-latest")
                yield Static("", id="buoy-extremes")
        yield Static("", id="buoy-status")

    def on_mount(self) -> None:
        eye = self.eye
        eye.poller.extra_buoys.add(self.station_id)
        if self.station_id not in eye.store.series:
            self.run_worker(eye.poll_now("buoys"), name="buoy-series", exit_on_error=False)
        self.run_worker(self._load_supplemental(), name="buoy-supl", exit_on_error=False)
        self._apply_layout(self.size.width)
        self.refresh_data()
        self.refresh_status()

    def on_unmount(self) -> None:
        self.eye.poller.extra_buoys.discard(self.station_id)

    def on_resize(self, event: Resize) -> None:
        self._apply_layout(event.size.width)
        self.refresh_status()

    def _apply_layout(self, width: int) -> None:
        narrow = width < NARROW_BELOW
        self.set_class(narrow, "narrow")
        self.set_class(narrow and self._show_info, "show-info")

    async def _load_supplemental(self) -> None:
        """One request, never retried: the extremes fall back to the regular rows when it fails."""
        try:
            self.supl = await self.eye.source.ndbc_supplemental(self.station_id)
            self.supl_note = self.supl.message if not self.supl.items else None
        except (FetchError, ParseError) as exc:
            self.supl = Parsed()
            self.supl_note = f"No supplemental file ({type(exc).__name__}); extremes use the regular rows."
        self.refresh_data()

    # ---- data -------------------------------------------------------------------------------------------------

    def refresh_status(self) -> None:
        self.query_one("#buoy-status", Static).update(self.eye.status_text(self.size.width))

    def refresh_data(self) -> None:
        eye = self.eye
        store, now, preset, tz, g = eye.store, eye.now(), eye.preset, eye.local_tz, eye.glyphs
        station = store.stations.get(self.station_id)
        state = st.buoy_state(store, self.station_id, now)
        head = Text(no_wrap=True, overflow="ellipsis")
        head.append(f" {self.station_id} ", style="bold #8fd3ff")
        head.append(st.short_name(station.name, 40) if station else "", style="bold")
        if station is not None:
            head.append(f"  {abs(station.lat):.2f}{'N' if station.lat >= 0 else 'S'} ", style=DIM)
            head.append(f"{abs(station.lon):.2f}{'E' if station.lon >= 0 else 'W'}", style=DIM)
        if state in ("silent", "dark"):
            head.append(f"  {st.NOT_REPORTING}", style="bold #ffa63d")
        elif state == "waiting":
            head.append("  waiting for data", style=DIM)
        head.append(f"  {self.hours} h", style=DIM)
        self.query_one("#buoy-title", Static).update(head)

        series = store.series.get(self.station_id)
        rows = list(series.observations) if series is not None else []
        if not rows:  # not polled yet: the latest_obs row is better than nothing
            latest = store.latest.get(self.station_id)
            rows = [latest.observation] if latest is not None else []
        lines = st.chart_series(rows, now, self.hours, preset)
        titles = {
            "pressure": f"Pressure ({LABELS[preset.pressure]})",
            "wind": f"Wind and gust ({LABELS[preset.wind]})",
            "wave": f"Wave height ({LABELS[preset.length]})",
        }
        ticks = st.time_ticks(self.hours)
        empty = st.NOT_REPORTING if state in ("silent", "dark") else "no data in this range"
        for key, chart_lines in lines.items():
            self.query_one(f"#chart-{key}", ChartView).set_chart(
                chart_lines, title=titles[key], x_range=(-float(self.hours), 0.0), x_ticks=ticks, empty=empty
            )
        for key, _title, field, _color in SPARK_FIELDS:
            spark = self.query_one(f"#spark-{key}", Sparkline)
            spark.data = st.sparkline_values(rows, now, self.hours, field)
            label = self.query_one(f"#spark-{key}-label", Static)
            label.update(Text(titles[key].split(" (")[0] + f"  {self.hours} h", style=DIM))

        obs = st.newest_observation(store, self.station_id)
        self.query_one("#buoy-latest", Static).update(
            st.latest_observation_text(obs, store, self.station_id, now, preset, g)
        )
        supplemental = list(self.supl.items) if self.supl is not None else []
        ext = st.extremes_for(rows, supplemental, now, self.hours)
        self.query_one("#buoy-extremes", Static).update(
            Text("\n").append_text(st.extremes_text(ext, self.hours, preset, tz, supl_note=self.supl_note))
        )

    # ---- actions ----------------------------------------------------------------------------------------------

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_range(self) -> None:
        self.range_index = (self.range_index + 1) % len(st.RANGES_H)
        self.refresh_data()

    def action_toggle_info(self) -> None:
        self._show_info = not self._show_info
        self._apply_layout(self.size.width)

    def action_pin(self) -> None:
        self.run_worker(self.eye.toggle_watch("ndbc", self.station_id), exclusive=False)
