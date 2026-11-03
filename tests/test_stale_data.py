"""Data is shown by age, not by presence: a tide series and an outlook GIS answer both carry a time and a threshold."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from eyewall.models.obs import Parsed, TideSeries, WaterLevelReading
from eyewall.models.outlook import GIS_DROP_AFTER, GIS_NOTE_AFTER, Outlook, OutlookGis, OutlookSystem
from eyewall.state import tides
from eyewall.ui.adapt import outlook_areas
from eyewall.ui.words import outlook as words
from tests.state_support import advisories, gauge
from tests.test_poll import build

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
RING = ((25.0, -60.0), (26.0, -60.0), (26.0, -59.0), (25.0, -59.0))


def _tide(station_id: str, age: timedelta) -> TideSeries:
    return TideSeries(station_id, "MLLW", water_level=Parsed((WaterLevelReading(NOW - age, 3.0),)))


def _system(p7: int = 40) -> OutlookSystem:
    return OutlookSystem("Atlantic", "1", 20, "low", p7, "medium", polygons=(RING,))


def _outlook(age: timedelta) -> Outlook:
    return Outlook(gis=OutlookGis(NOW - age, (_system(),)))


# ---- CO-OPS series (#138) -------------------------------------------------------------------------------------


async def test_a_series_for_a_gauge_that_left_the_polled_set_is_dropped():
    poller, source, store, clock, _ = build()
    clock.set(NOW)
    source.tide_stations = (gauge("8000001", 25.5, -75.5),)
    source.set_storm("1")
    source.texts["1"] = advisories("1")
    store.tide_series["9999999"] = _tide("9999999", timedelta(minutes=6))  # polled once, since gone
    await poller.tick()
    assert "9999999" not in store.tide_series
    assert "8000001" in store.tide_series


async def test_a_series_whose_newest_level_is_past_the_drop_threshold_is_dropped_and_a_recent_one_kept():
    poller, source, store, clock, _ = build()
    clock.set(NOW)
    source.tide_stations = (gauge("8000001", 25.5, -75.5), gauge("8000002", 25.6, -75.6))
    ages = {"8000001": tides.DROP_AFTER + timedelta(minutes=1), "8000002": tides.SILENT_AFTER}

    async def coops_series(station, datum):
        return _tide(station.id, ages[station.id])

    source.coops_series = coops_series
    source.set_storm("1")
    source.texts["1"] = advisories("1")
    await poller.tick()
    assert set(store.tide_series) == {"8000002"}


async def test_a_gauge_page_that_is_open_keeps_its_series_polled():
    poller, source, _store, clock, _ = build()
    clock.set(NOW)
    source.tide_stations = (gauge("8000001", 25.5, -75.5),)
    poller.extra_gauges.add("8000001")  # no storm, no watchlist: only the open page wants it
    await poller.tick()
    assert [d for d in source.datums if d[0] == "8000001"]


@given(st.integers(0, 10 * 24 * 3600))
def test_the_tide_age_is_never_negative_and_expiry_follows_it(seconds):
    series = _tide("1", timedelta(seconds=seconds))
    assert tides.observation_age(series, NOW) == timedelta(seconds=seconds)
    assert tides.is_expired(series, NOW) == (seconds > tides.DROP_AFTER.total_seconds())
    future = _tide("1", timedelta(seconds=-seconds))
    assert tides.observation_age(future, NOW) == timedelta(0)


# ---- outlook GIS (#139) ---------------------------------------------------------------------------------------


def test_a_fresh_outlook_label_carries_no_age():
    (area,) = outlook_areas(_outlook(timedelta(hours=2)), NOW)
    assert area.label == "40% in 7 days"


def test_an_old_outlook_label_says_how_old_it_is():
    (area,) = outlook_areas(_outlook(timedelta(hours=14)), NOW)
    assert area.label == "40% in 7 days, 14h00m old"


def test_an_outlook_past_the_drop_threshold_is_not_drawn():
    assert outlook_areas(_outlook(GIS_DROP_AFTER + timedelta(minutes=1)), NOW) == ()


def test_a_kept_gis_copy_does_not_win_over_fresh_text_areas():
    from eyewall.models.outlook import Chance, OutlookArea, OutlookText

    text = OutlookText(
        "NHC Miami FL",
        NOW,
        None,
        "Atlantic",
        None,
        (OutlookArea(1, "", None, "", Chance("low", 10), Chance("low", 20)),),
        "",
        "",
        None,
    )
    old = Outlook(texts=(text,), gis=OutlookGis(NOW - timedelta(hours=48), (_system(70),)))
    assert "70%" in words.outlook_sentences(old, ["AL"])[0].text  # without an age, the shapes speak
    sentences = words.outlook_sentences(old, ["AL"], now=NOW)
    assert "20%" in sentences[0].text and "70%" not in sentences[0].text


@given(st.integers(-48 * 3600, 96 * 3600))
def test_the_gis_age_is_never_negative_and_the_thresholds_order_it(seconds):
    gis = OutlookGis(NOW - timedelta(seconds=seconds), (_system(),))
    age = gis.age(NOW)
    assert age is not None and age >= timedelta(0)
    assert gis.expired(NOW) == (seconds > GIS_DROP_AFTER.total_seconds())
    assert GIS_NOTE_AFTER < GIS_DROP_AFTER


def test_a_gis_without_a_time_is_never_aged_out():
    gis = OutlookGis(None, (_system(),))
    assert gis.age(NOW) is None and not gis.expired(NOW)
