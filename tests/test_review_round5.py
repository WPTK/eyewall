"""Regression tests for the round 5 review: one current advisory number, honest ages, no stale picture, clean text."""

from __future__ import annotations

import io
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from rich.console import Console

from eyewall.clock import VirtualClock
from eyewall.config import Config
from eyewall.models.advisory import AdvisorySet, PublicSummary
from eyewall.models.obs import Observation
from eyewall.net import FetchError
from eyewall.sources.live import LiveSource
from eyewall.state.store import Store, StormState
from eyewall.state.trends import wave_trend, wind_trend
from eyewall.textclean import printable
from eyewall.ui import nhc_text, products
from eyewall.ui.glyphs import glyphs_for
from eyewall.ui.widgets import storm_cards
from eyewall.ui.widgets.side_panel import View
from eyewall.ui.words import Words
from eyewall.ui.words import station as station_words
from eyewall.ui.words import storm as sw
from eyewall.ui.words import summary as summary_words
from eyewall.units import PRESETS
from tests.state_support import T0, make_forecast, make_public, make_storm

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


# ---- P1-1: a cached picture is not the new advisory's picture -------------------------------------------------------


async def test_a_picture_the_cache_supplied_after_a_failure_is_not_returned(tmp_path):
    fail = {"on": False}

    def handler(request):
        if fail["on"]:
            return httpx.Response(503)
        return httpx.Response(200, content=b"\x89PNG\r\n\x1a\n" + b"0" * 64, headers={"content-type": "image/png"})

    source = LiveSource(cache_dir=tmp_path, transport=httpx.MockTransport(handler), clock=VirtualClock(NOW))
    url = "https://www.nhc.noaa.gov/storm_graphics/AT05/AL052025_5day_cone.png"
    try:
        assert await source.image(url)
        fail["on"] = True
        with pytest.raises(FetchError):
            await source.image(url)
    finally:
        await source.aclose()


# ---- P1-2 / P2: the intermediate advisory is the current one --------------------------------------------------------


def state_at_31a() -> StormState:
    storm = make_storm("31A", intermediate_only=True)
    advisories = AdvisorySet(forecast=make_forecast("31"), public=make_public("31"))
    return StormState(storm, advisories)


def test_the_public_tab_at_31_warns_when_the_feed_is_at_31a():
    state = state_at_31a()
    header = nhc_text.storm_header(state, "public", T0, None, glyphs_for("unicode"), feed_old=False, feed_age=None)
    assert header.stale is not None and "31A" in header.stale


def test_the_forecast_tab_at_31_is_current_at_31a():
    state = state_at_31a()
    header = nhc_text.storm_header(state, "forecast", T0, None, glyphs_for("unicode"), feed_old=False, feed_age=None)
    assert header.stale is None


def make_view(state: StormState) -> View:
    return View(
        store=Store(Config()),
        preset=PRESETS["us"],
        now=T0,
        g=glyphs_for("unicode"),
        tz=None,
        states=(state,),
        selected=state.storm.id,
        basins=(),
        replay_offer=None,
        storms_known=True,
        failed=frozenset(),
    )


def test_the_strip_and_the_summary_show_the_current_advisory_not_the_tcms():
    state = state_at_31a()
    line = storm_cards.strip_line(make_view(state), 120)
    assert line is not None and "adv 31A" in line.text.plain
    console = Console(width=100, record=True, file=io.StringIO())
    console.print(products.summary(state, T0, PRESETS["us"], None))
    assert "31A" in console.export_text()


# ---- P1-4: knots from the TCM only when it is the same advisory ------------------------------------------------------


def test_knots_and_kmh_do_not_take_the_previous_advisorys_speed():
    state = state_at_31a()
    summary = PublicSummary(movement_dir_deg=300, movement_speed_mph=20)
    public = replace(make_public("31A"), summary=summary)
    tcm = replace(make_forecast("31"), movement_speed_kt=9)
    state = replace(state, advisories=AdvisorySet(forecast=tcm, public=public))
    assert "20 mph" in sw.storm_lead(state, PRESETS["us"]).text
    assert "17 kt" in sw.storm_lead(state, PRESETS["nautical"]).text  # 20 mph, not the old TCM's 9 kt
    assert "32 km/h" in sw.storm_lead(state, PRESETS["metric"]).text


def test_the_tcm_of_the_same_advisory_still_supplies_the_knots():
    summary = PublicSummary(movement_dir_deg=300, movement_speed_mph=20)
    public = replace(make_public("31"), summary=summary)
    tcm = replace(make_forecast("31"), movement_speed_kt=17)
    state = StormState(make_storm("31"), AdvisorySet(forecast=tcm, public=public))
    assert "17 kt" in sw.storm_lead(state, PRESETS["nautical"]).text


# ---- P1-3: trends from old readings are not "the last 3 hours" -------------------------------------------------------


def _rows(newest_age_h: float, **values: float) -> list[Observation]:
    base = NOW - timedelta(hours=newest_age_h)
    return [Observation(time=base - timedelta(hours=h), **values) for h in (0, 3)]


def test_a_wind_or_wave_trend_from_a_reading_hours_old_is_dropped():
    wind = [replace(o, wind_speed_mps=5.0 + i * 5) for i, o in enumerate(_rows(6))]
    waves = [replace(o, wave_height_m=1.0 + i) for i, o in enumerate(_rows(6))]
    assert wind_trend(wind) is not None  # without a clock the old behaviour holds
    assert wind_trend(wind, now=NOW) is None
    assert wave_trend(waves, now=NOW) is None


def test_a_fresh_wind_trend_is_kept_and_the_sentence_is_absent_for_none():
    wind = [replace(o, wind_speed_mps=5.0 + i * 5) for i, o in enumerate(_rows(0.5))]
    assert wind_trend(wind, now=NOW) is not None
    assert station_words.wind_trend_sentence(None, PRESETS["us"]) is None


# ---- P1-5: --summary says when it could not read the warnings --------------------------------------------------------


def test_the_summary_says_when_the_watches_and_warnings_are_not_read():
    state = StormState(make_storm("31A"), AdvisorySet(forecast=make_forecast("31")))
    texts = [w.text for w in summary_words._storm_block(state, PRESETS["us"], T0, None)]
    assert "Its watches and warnings are not yet read for advisory 31A." in texts


def test_the_summary_is_silent_about_it_when_the_list_was_read():
    state = StormState(make_storm("31"), AdvisorySet(forecast=make_forecast("31"), public=make_public("31")))
    texts = [w.text for w in summary_words._storm_block(state, PRESETS["us"], T0, None)]
    assert not any("not yet read" in t for t in texts)


# ---- P2: control characters never reach the terminal -----------------------------------------------------------------


def test_printable_strips_escapes_and_controls_but_keeps_text_tab_and_newline():
    assert printable("Er\x1b[2Jin\x07\x00 \x9b\x7f") == "Er[2Jin "
    assert printable("a\tb\nc") == "a\tb\nc"
    assert printable("Zoë Ñ") == "Zoë Ñ"


def test_words_and_wrapped_text_are_cleaned():
    from eyewall.ui.widgets.side_panel import wrapped

    assert Words("Storm \x1b]0;x\x07Erin").text == "Storm ]0;xErin"
    assert "\x1b" not in wrapped("Erin \x1b[31m red", 40)[0].text.plain


def test_a_manifest_with_escapes_in_its_names_is_cleaned(tmp_path):
    from eyewall.sources.bundle import Manifest, read_manifest, write_manifest

    manifest = Manifest("demo\x1b[2J", "al052025", "ERIN\x1b]0;x", "AT5", T0, T0, title="T\x1bitle")
    write_manifest(tmp_path, manifest)
    read = read_manifest(tmp_path)
    assert (read.name, read.storm_name, read.title) == ("demo[2J", "ERIN]0;x", "Title")


async def test_toasts_are_shown_as_plain_text(monkeypatch):
    from eyewall.models.events import Event, EventKind
    from tests.ui_support import replay_app, running

    event = Event(next(iter(EventKind)), "k", "[/] Erin [bold]", T0)
    app = replay_app()
    seen: list[dict[str, object]] = []
    async with running(app, (100, 40)):
        monkeypatch.setattr(app, "notify", lambda message, **kw: seen.append({"message": message, **kw}))
        app._show_events([event])
    assert seen and all(call["markup"] is False for call in seen)


def test_escape_sequences_in_advisory_bodies_are_stripped_at_parse():
    from eyewall.providers.nhc.tcm import parse_tcm
    from eyewall.providers.nhc.text import parse_tcd, parse_tcp, parse_two
    from tests.nhc_fixtures import nhc_text

    raw = nhc_text("tcp/erin_030.txt")
    dirty = raw.replace("SUMMARY OF", "\x1b[2J\x07SUMMARY OF", 1).replace("HURRICANE", "HURRI\x1b]0;x\x07CANE")
    assert "\x1b" in dirty
    public = parse_tcp(dirty)
    assert "\x1b" not in repr(public) and "\x07" not in repr(public)
    for fixture, parser in (("tcd/erin_030.txt", parse_tcd), ("tcm/erin_030.txt", parse_tcm)):
        body = nhc_text(fixture).replace("ERIN ", "ERIN\x1b\x07 ", 1)
        assert "\x1b" not in repr(parser(body))
    assert callable(parse_two)
