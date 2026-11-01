"""The whole picture in plain sentences, for `eyewall --summary`: storms, what is in effect, nearby reports, outlook."""

from __future__ import annotations

from datetime import datetime, tzinfo

from eyewall.models.obs import Station
from eyewall.state.nearby import NearbyStation
from eyewall.state.store import Store, StormState
from eyewall.state.trends import wave_trend, wind_trend
from eyewall.ui import stations as st
from eyewall.ui.words import Words
from eyewall.ui.words import outlook as outlook_words
from eyewall.ui.words import station as station_words
from eyewall.ui.words import storm as storm_words
from eyewall.units import Preset

MAX_BUOYS = 5
MAX_GAUGES = 3


def _storm_block(state: StormState, preset: Preset, now: datetime, tz: tzinfo | None) -> list[Words]:
    out = [storm_words.storm_lead(state, preset)]
    for words in (
        storm_words.storm_wind(state, preset),
        *storm_words.warning_sentences(state),
        *storm_words.meaning_sentences(state),
        storm_words.size_sentence(state, preset),
        storm_words.strongest(state, tz),
        storm_words.updated(state.storm, now),
        storm_words.next_advisory(state),
    ):
        if words is not None:
            out.append(words)
    return out


def _buoy_line(
    store: Store, entry: NearbyStation[Station], storm_name: str, preset: Preset, now: datetime, tz: tzinfo | None
) -> str | None:
    station_id = entry.station.id
    obs = st.newest_observation(store, station_id)
    state = st.buoy_state(store, station_id, now)
    if state != "ok" or obs is None:
        gap = station_words.state_sentence(state, obs, now, tz)
        label = f"Buoy {station_id}" + (f" ({entry.station.name})" if entry.station.name else "")
        return None if gap is None else f"{label}: {gap.text}"
    series = store.series.get(station_id.upper())
    rows = () if series is None else series.observations
    waves = st.last_reading(store, station_id, obs, now, "wave_height_m")
    parts = [
        station_words.buoy_lead(entry, storm_name, obs, waves, preset),
        station_words.pressure_trend(store.tendency(station_id, now), preset),
        station_words.wind_trend_sentence(wind_trend(rows), preset),
        station_words.wave_trend_sentence(wave_trend(rows), preset),
        station_words.approach_sentence(entry, preset),
    ]
    return " ".join(p.text for p in parts if p is not None)


def summary_lines(store: Store, preset: Preset, now: datetime, tz: tzinfo | None = None) -> list[str]:
    """The summary as lines of plain text; an empty line separates the parts."""
    enabled = store.config.basins.enabled
    blocks: list[list[str]] = []
    states = sorted(store.storms.values(), key=lambda s: s.storm.id)
    if not states:
        blocks.append([storm_words.nothing_active(enabled).text])
    elif len(states) > 1:
        blocks.append([storm_words.several_storms(states).text])
    for state in states:
        block = [w.text for w in _storm_block(state, preset, now, tz)]
        storm_id = state.storm.id
        lines = (
            _buoy_line(store, e, state.storm.name, preset, now, tz)
            for e in store.nearby_buoys(storm_id, now)[:MAX_BUOYS]
        )
        buoys = [line for line in lines if line]
        gauges = [
            station_words.gauge_sentence(e.station, store.tide_series.get(e.station.id), now, preset).text
            for e in store.nearby_tides(storm_id, now)[:MAX_GAUGES]
        ]
        blocks.append(block + buoys + gauges)
    blocks.append([w.text for w in outlook_words.outlook_sentences(store.outlook, enabled)])
    out: list[str] = []
    for block in blocks:
        if out:
            out.append("")
        out.extend(block)
    return out
