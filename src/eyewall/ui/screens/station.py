"""The Station screen: one buoy or tide gauge in plain words, with its charts or, on `r`, its table of readings.

The series comes from the poller (the 5 day file covers the longest range); the page asks for the station when it opens,
so a station that was not near any storm still has something to show.
"""

from __future__ import annotations

from datetime import datetime
from typing import cast

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.events import Resize
from textual.message import Message
from textual.widgets import Static

from eyewall.clock import format_age
from eyewall.config import watchlist_ids
from eyewall.models.obs import Parsed, Station, SupplementalReading, TideStation
from eyewall.net import FetchError
from eyewall.palette import DIM, FRESHNESS_CUES, GUST_SERIES, PRESSURE_SERIES, TIDE_GAUGE, WIND_SERIES
from eyewall.providers.base import ParseError
from eyewall.render.chart import ChartSeries
from eyewall.state.nearby import NearbyStation
from eyewall.state.tides import is_silent, observation_age
from eyewall.state.trends import wave_trend, wind_trend
from eyewall.ui import nav, station_view
from eyewall.ui import stations as st
from eyewall.ui.chrome import ChromeScreen, FooterBar, TopBar
from eyewall.ui.widgets.chart_view import ChartView
from eyewall.ui.words import station as words
from eyewall.units import LABELS, convert

BUOY_CHARTS = ("pressure", "wind", "wave")
GAUGE_CHARTS = ("level", "gwind", "gpressure")

CHART_ROWS = 6  # the least a chart is given: its legend, a plot you can read, the axis and its labels
CHART_NAMES = {
    "pressure": "pressure",
    "wind": "wind",
    "wave": "wave",
    "level": "water level",
    "gwind": "wind",
    "gpressure": "pressure",
}
SMALL_HEIGHT = 30  # rows under which the lead drops the third trend and the extremes line


class FollowLine(Static):
    """The follow state in words, and a control: a click does what `f` does."""

    async def on_click(self, event: events.Click) -> None:
        event.stop()
        await self.screen.run_action("follow")


class ChartStack(Vertical):
    """The charts' room. When its height changes the screen decides again how many charts fit."""

    class Resized(Message):
        pass

    def on_resize(self, event: Resize) -> None:
        self.post_message(self.Resized())


class StationScreen(ChromeScreen):
    NAV_SCOPES = ("station",)
    BINDINGS = nav.bindings("station")

    def __init__(self, kind: str, station_id: str) -> None:
        super().__init__()
        self.kind = kind
        self.station_id = station_id.upper()
        self.range_index = 0
        self.chart_page = 0  # which group of charts shows when the screen is too short for all of them
        self._visible: tuple[str, ...] = ()
        self.readings = False
        self.about = False
        self.supl: Parsed[SupplementalReading] | None = None
        self._supl_loading = False
        self.series_error: str | None = None  # why the buoy's readings could not be fetched, when they could not

    def crumb(self) -> str:
        return f"{station_view.KIND_WORD[self.kind]} {self.station_id}"

    @property
    def hours(self) -> int:
        return st.RANGES_H[self.range_index]

    @property
    def is_buoy(self) -> bool:
        return self.kind == station_view.BUOY

    def compose(self) -> ComposeResult:
        yield TopBar()
        yield Static("", id="station-lead")
        yield FollowLine("", id="station-follow")
        yield Static("", id="station-about")
        with ChartStack(id="station-charts"):
            for name in (*BUOY_CHARTS, *GAUGE_CHARTS):
                yield ChartView(mode=self.eye.map_mode, id=f"chart-{name}")
            yield Static("", id="station-more")
        with VerticalScroll(id="station-readings"):
            yield Static("", id="station-table")
        yield FooterBar()

    def on_mount(self) -> None:
        eye = self.eye
        self.query_one("#station-readings").display = False
        self.query_one("#station-about").display = False
        if self.is_buoy:
            eye.poller.extra_buoys.add(self.station_id)
            if self.station_id not in eye.store.series:
                self.run_worker(self._load_series(), name="station-series", exit_on_error=False)
            self._ask_supplemental()
        else:
            self.run_worker(self._load_gauge(), name="station-gauge", exit_on_error=False)
        self._draw()

    def on_unmount(self) -> None:
        # Another page for the same station may still be open beneath or above this one; it still needs the polling.
        others = [
            s
            for s in self.app.screen_stack
            if s is not self and isinstance(s, StationScreen) and s.is_buoy and s.station_id == self.station_id
        ]
        if not others:
            self.eye.poller.extra_buoys.discard(self.station_id)

    async def _load_series(self) -> None:
        self.series_error = await self.eye.fetch_series(self.station_id)
        self._draw()

    def on_resize(self, event: Resize) -> None:
        self._draw()

    async def _load_gauge(self) -> None:
        eye = self.eye
        if not eye.store.tide_stations:
            await eye.ensure_catalogs()
        if self.station_id not in eye.store.tide_series:
            await eye.fetch_tide(self.station_id)
        self._draw()

    def _ask_supplemental(self) -> None:
        if self._supl_loading:
            return
        self._supl_loading = True
        self.run_worker(self._load_supplemental(), name="station-supl", group="station-supl", exit_on_error=False)

    async def _load_supplemental(self) -> None:
        try:
            self.supl = await self.eye.supplemental(self.station_id)
        except (FetchError, ParseError):
            self.supl = self.supl or Parsed()
        finally:
            self._supl_loading = False
        self._draw()

    # ---- data -------------------------------------------------------------------------------------------------

    def refresh_data(self) -> None:
        if self.is_buoy:
            self._ask_supplemental()
        self._draw()

    def _followed(self) -> bool:
        return self.station_id in {w.upper() for w in watchlist_ids(self.eye.config, self.kind)}

    def _entry(self) -> NearbyStation[Station] | NearbyStation[TideStation] | None:
        """The station's place relative to the selected storm, when it is one of the stations near it."""
        eye = self.eye
        storm_id = eye.selected
        if storm_id is None:
            return None
        found = (
            eye.store.nearby_buoys(storm_id, eye.now()) if self.is_buoy else eye.store.nearby_tides(storm_id, eye.now())
        )
        return next((e for e in found if e.station.id.upper() == self.station_id), None)

    def _stale(self, sentence: str) -> str:
        eye = self.eye
        cue = FRESHNESS_CUES["stale"]
        glyph = cue.ascii_glyph if eye.config.map.glyph_set == "ascii" else cue.glyph
        return f"{glyph} {cue.word.capitalize()}: {sentence}"

    def _lead(self) -> list[tuple[str, str]]:
        """(text, style) paragraphs at the top: what it reads now, the trends, the storm's approach."""
        if self.is_buoy:
            return self._buoy_lead()
        return self._gauge_lead()

    def _buoy_lead(self) -> list[tuple[str, str]]:
        eye = self.eye
        store, now, preset, tz, g = eye.store, eye.now(), eye.preset, eye.local_tz, eye.glyphs
        station = store.stations.get(self.station_id) or Station(self.station_id, "", 0.0, 0.0)
        state = st.buoy_state(store, self.station_id, now)
        obs = st.newest_observation(store, self.station_id)
        entry = cast("NearbyStation[Station] | None", self._entry())
        storm = store.storms.get(eye.selected or "")
        out: list[tuple[str, str]] = []
        small = self.size.height < SMALL_HEIGHT
        if state == "ok" and obs is not None:
            waves = st.last_reading(store, self.station_id, obs, now, "wave_height_m")
            if entry is not None and storm is not None:
                lead = words.buoy_lead(entry, storm.storm.name.title() or storm.storm.id.upper(), obs, waves, preset)
            else:
                lead = words.buoy_summary(station, obs, waves, preset)
            out.append((lead.text, "bold"))
            out.append((f"{g.sep} Observed {format_age(max(0.0, (now - obs.time).total_seconds()))} ago.", ""))
            series = store.series.get(self.station_id)
            rows = () if series is None else series.observations
            trends = (
                words.pressure_trend(store.tendency(self.station_id, now), preset),
                words.wind_trend_sentence(wind_trend(rows), preset),
                words.wave_trend_sentence(wave_trend(rows), preset),
            )
            shown = [t for t in trends if t is not None]
            for trend in shown[:2] if small else shown:  # a short screen keeps room for the charts
                out.append((f"{g.sep} {trend.text}", ""))
        else:
            name = f" ({station.name})" if station.name else ""
            out.append((f"Buoy {self.station_id}{name}", "bold"))
            gap = words.state_sentence(state, obs, now, tz)
            if state == "silent":
                out.append((self._stale(gap.text if gap else "No recent report."), FRESHNESS_CUES["stale"].style()))
            else:
                out.append((gap.text if gap else "Not reporting.", DIM))
        if entry is not None:
            out.append((words.approach_sentence(entry, preset).text, ""))
        ext = st.extremes_for(
            list(store.series[self.station_id].observations) if self.station_id in store.series else [],
            list(self.supl.items) if self.supl is not None else [],
            now,
            self.hours,
        )
        extremes = None if small else words.extremes_sentence(ext, preset, tz)
        if extremes is not None:
            out.append((f"Last {self.hours} hours: {extremes.text}", DIM))
        return out

    def _gauge_lead(self) -> list[tuple[str, str]]:
        eye = self.eye
        store, now, preset, g = eye.store, eye.now(), eye.preset, eye.glyphs
        gauge = next((t for t in store.tide_stations if t.id.upper() == self.station_id), None)
        station = gauge or TideStation(self.station_id, "", 0.0, 0.0)
        series = store.tide_series.get(self.station_id)
        out: list[tuple[str, str]] = []
        label = f"Gauge {self.station_id}" + (f" ({station.name})" if station.name else "")
        if series is None or series.latest_level is None:
            out.append((label, "bold"))
            failed = self.station_id in store.tide_errors or series is not None
            out.append(
                (
                    "Not reporting. Could not fetch the water level for this gauge."
                    if self.station_id in store.tide_errors
                    else "Not reporting. NOAA has no recent water level for this gauge."
                    if failed
                    else "Waiting for the first water level.",
                    DIM,
                )
            )
        else:
            age = observation_age(series, now)
            sentence = words.gauge_sentence(station, series, now, preset).text
            if age is not None and is_silent(series, now):
                out.append((label, "bold"))
                out.append((self._stale(sentence), FRESHNESS_CUES["stale"].style()))
            else:
                out.append((sentence, "bold"))
                if age is not None:
                    out.append((f"{g.sep} Last reading {format_age(age.total_seconds())} ago.", ""))
            wind = st.tide_wind(series, now)
            pressure = st.tide_pressure(series, now)
            parts = []
            if wind is not None:
                direction = f"{wind.direction_text} " if wind.direction_text else ""
                parts.append(f"wind {direction}{preset.fmt_wind(wind.speed_kt)}")
            if pressure is not None:
                parts.append(f"pressure {preset.fmt_pressure(pressure.pressure_mb, 'mb')}")
            if parts:
                out.append((f"{g.sep} The gauge also reads {' and '.join(parts)}.", ""))
        entry = self._entry()
        if entry is not None:
            out.append((words.approach_sentence(entry, preset).text, ""))
        return out

    def _draw(self) -> None:
        if not self.is_attached:
            return
        paragraphs = self._lead()
        lead = Text()
        for index, (text, style) in enumerate(paragraphs):
            if index:
                lead.append("\n")
            lead.append(text, style=style)
        self.query_one("#station-lead", Static).update(lead)
        mark = "*" if self._followed() else "-"
        words_ = (
            "Following this station. Click here or press f to stop."
            if self._followed()
            else "Not following. Click here or press f to follow this station."
        )
        self.query_one("#station-follow", Static).update(Text(f"{mark} {words_}", style="bold underline"))
        about = self.query_one("#station-about", Static)
        about.display = self.about
        if self.about:
            about.update(Text(words.about_buoy_winds().text, style=DIM))
        self.query_one("#station-readings").display = self.readings
        self.query_one("#station-charts").display = not self.readings
        if self.readings:
            self._draw_readings()
        else:
            self._draw_charts()
        self.refresh_bindings()

    def _draw_charts(self) -> None:
        eye = self.eye
        store, now, preset = eye.store, eye.now(), eye.preset
        hours = float(self.hours)
        ticks = st.time_ticks(hours)
        x_range = (-hours, 0.0)
        show = BUOY_CHARTS if self.is_buoy else GAUGE_CHARTS
        self._visible = self._chart_page(show)
        for name in (*BUOY_CHARTS, *GAUGE_CHARTS):
            self.query_one(f"#chart-{name}").display = name in self._visible
        if self.is_buoy:
            series = store.series.get(self.station_id)
            rows = list(series.observations) if series is not None else []
            if not rows:
                latest = store.latest.get(self.station_id)
                rows = [latest.observation] if latest is not None else []
            state = st.buoy_state(store, self.station_id, now)
            if not rows and self.series_error is not None:
                empty = "Could not load readings"  # the fetch failed here: that says more than "not reporting"
            elif state in ("silent", "dark"):
                empty = st.NOT_REPORTING
            else:
                empty = "no data in this range"
            lines = st.chart_series(rows, now, hours, preset)
            titles = {
                "pressure": f"Pressure ({LABELS[preset.pressure]})",
                "wind": f"Wind and gust ({LABELS[preset.wind]})",
                "wave": f"Wave height ({LABELS[preset.length]})",
            }
            for key, chart_lines in lines.items():
                self._chart(key).set_chart(chart_lines, title=titles[key], x_range=x_range, x_ticks=ticks, empty=empty)
            return
        tide = store.tide_series.get(self.station_id)
        empty = "no data in this range" if tide is not None else "waiting for data"
        length = preset.length
        observed = ChartSeries(
            "observed",
            tuple(
                (x, None if y is None else convert(y, "ft", length))
                for x, y in station_view.gauge_levels(tide, now, hours)
            ),
            TIDE_GAUGE,
        )
        predicted = ChartSeries(
            "predicted",
            tuple(
                (x, None if y is None else convert(y, "ft", length))
                for x, y in station_view.gauge_predictions(tide, now, hours)
            ),
            DIM,
        )
        datum = f" above {tide.datum}" if tide is not None else ""
        self._chart("level").set_chart(
            [observed, predicted],
            title=f"Water level ({LABELS[length]}{datum})",
            x_range=x_range,
            x_ticks=ticks,
            empty=empty,
        )
        wind_points = self._gauge_points(
            tide.wind.items if tide else (), now, hours, lambda w: w.speed_kt, "kt", preset.wind
        )
        gust_points = self._gauge_points(
            tide.wind.items if tide else (), now, hours, lambda w: w.gust_kt, "kt", preset.wind
        )
        self._chart("gwind").set_chart(
            [ChartSeries("wind", wind_points, WIND_SERIES), ChartSeries("gust", gust_points, GUST_SERIES)],
            title=f"Wind and gust ({LABELS[preset.wind]})",
            x_range=x_range,
            x_ticks=ticks,
            empty="this gauge has no wind sensor" if tide is not None and not tide.wind.items else empty,
        )
        pressure_points = self._gauge_points(
            tide.pressure.items if tide else (), now, hours, lambda p: p.pressure_mb, "mb", preset.pressure
        )
        self._chart("gpressure").set_chart(
            [ChartSeries("pressure", pressure_points, PRESSURE_SERIES)],
            title=f"Pressure ({LABELS[preset.pressure]})",
            x_range=x_range,
            x_ticks=ticks,
            empty="this gauge has no pressure sensor" if tide is not None and not tide.pressure.items else empty,
        )

    def _chart_page(self, show: tuple[str, ...]) -> tuple[str, ...]:
        """The charts to show now. Each gets at least CHART_ROWS rows; when they do not all fit, the screen shows as
        many as do, with a line that says there are more and how to reach them."""
        height = self.query_one("#station-charts").size.height
        per = len(show) if height <= 0 else max(1, height // CHART_ROWS)
        more = self.query_one("#station-more", Static)
        if per >= len(show):
            self.chart_page = 0
            more.display = False
            return show
        per = max(1, (height - 1) // CHART_ROWS)  # a row for the line about the others
        pages = -(-len(show) // per)
        self.chart_page %= pages
        shown = show[self.chart_page * per : (self.chart_page + 1) * per]
        names = " and ".join(CHART_NAMES[n] for n in shown)
        more.update(
            Text(
                f"{names.capitalize()} chart, {self.chart_page + 1} of {pages}. More charts: tab. All numbers: r.",
                style=DIM,
            )
        )
        more.display = True
        return shown

    def on_chart_stack_resized(self, event: ChartStack.Resized) -> None:
        event.stop()
        if not self.readings:
            self._draw_charts()

    @staticmethod
    def _gauge_points(
        items: object, now: datetime, hours: float, value: object, source: str, target: str
    ) -> tuple[tuple[float, float | None], ...]:
        points: list[tuple[float, float | None]] = []
        for item in items:  # type: ignore[attr-defined]
            moment = item.time
            raw = value(item)  # type: ignore[operator]
            age_h = (now - moment).total_seconds() / 3600.0
            if 0 <= age_h <= hours:
                points.append((-age_h, None if raw is None else convert(raw, source, target)))
        return tuple(sorted(points))

    def _chart(self, name: str) -> ChartView:
        return self.query_one(f"#chart-{name}", ChartView)

    def _draw_readings(self) -> None:
        eye = self.eye
        store, now, preset, tz, g = eye.store, eye.now(), eye.preset, eye.local_tz, eye.glyphs
        out = Text()
        if self.is_buoy:
            obs = st.newest_observation(store, self.station_id)
            out.append_text(st.latest_observation_text(obs, store, self.station_id, now, preset, g))
            series = store.series.get(self.station_id)
            out.append(f"\nReadings in the last {self.hours} hours, newest first\n", style="bold")
            out.append_text(
                station_view.readings_table(list(series.observations) if series else [], now, self.hours, preset, tz)
            )
        else:
            tide = store.tide_series.get(self.station_id)
            out.append(f"Readings in the last {self.hours} hours, newest first\n", style="bold")
            if tide is None:
                out.append("Waiting for the first water level.", style=DIM)
            else:
                out.append_text(station_view.tide_readings_table(tide, now, self.hours, preset, tz))
        self.query_one("#station-table", Static).update(out)

    def on_chart_view_measured(self, event: ChartView.Measured) -> None:
        event.stop()
        charts = [c for c in self.query(ChartView) if c.display]
        widest = max((c.natural_gutter for c in charts), default=0)
        for chart in charts:
            chart.align(widest)

    # ---- actions ----------------------------------------------------------------------------------------------

    def check_action(self, action: str, _parameters: tuple[object, ...]) -> bool | None:
        if action == "about":
            return self.is_buoy
        if action == "next_chart":
            return not self.readings
        if action == "show_on_map":
            return self._position() is not None
        return True

    def _position(self) -> tuple[float, float] | None:
        store = self.eye.store
        if self.is_buoy:
            station = store.stations.get(self.station_id)
            return None if station is None else (station.lat, station.lon)
        gauge = next((t for t in store.tide_stations if t.id.upper() == self.station_id), None)
        return None if gauge is None else (gauge.lat, gauge.lon)

    def action_range(self) -> None:
        self.range_index = (self.range_index + 1) % len(st.RANGES_H)
        self.notify(f"Showing the last {self.hours} hours.", timeout=2)
        self._draw()

    def action_next_chart(self) -> None:
        """Tab: the next chart (or pair) when the screen is too short for all of them."""
        self.chart_page += 1
        self._draw()

    def action_view(self) -> None:
        self.readings = not self.readings
        self._draw()

    def action_about(self) -> None:
        self.about = not self.about
        self._draw()

    def action_follow(self) -> None:
        self.eye.watch_in_background(self.kind, self.station_id, not self._followed())

    def action_show_on_map(self) -> None:
        position = self._position()
        if position is not None:
            self.app.call_later(self.eye.show_on_map, position[0], position[1], f"{self.crumb()}")


__all__ = ["StationScreen"]
