"""Data is shown by age, not by presence: a tide series and an outlook GIS answer both carry a time and a threshold."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from hypothesis import given
from hypothesis import strategies as st

from eyewall.config import Config, WatchlistConfig
from eyewall.models.obs import Parsed, TideSeries, WaterLevelReading
from eyewall.models.outlook import (
    GIS_DROP_AFTER,
    GIS_NOTE_AFTER,
    Chance,
    Outlook,
    OutlookArea,
    OutlookGis,
    OutlookSystem,
    OutlookText,
)
from eyewall.sources import protocol
from eyewall.state import tides
from eyewall.state.store import Store
from eyewall.ui.adapt import outlook_areas
from eyewall.ui.widgets.side_info import outlook_text
from eyewall.ui.words import outlook as words
from eyewall.ui.words.summary import summary_lines
from eyewall.units import PRESETS
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
    assert (
        "70%" in words.outlook_sentences(old, ["AL"], NOW - timedelta(hours=40))[0].text
    )  # while young, the shapes speak
    sentences = words.outlook_sentences(old, ["AL"], NOW)
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


def _text_outlook(gis_age: timedelta) -> Outlook:
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
    return Outlook(texts=(text,), gis=OutlookGis(NOW - gis_age, (_system(70),)))


def test_the_plain_summary_hides_an_expired_gis_like_the_map_does():
    store = Store(Config())
    store.outlook = _text_outlook(timedelta(hours=40))
    said = " ".join(summary_lines(store, PRESETS["us"], NOW))
    assert "20%" in said and "70%" not in said
    store.outlook = _text_outlook(timedelta(hours=2))
    assert "70%" in " ".join(summary_lines(store, PRESETS["us"], NOW))


def test_the_side_panel_and_the_area_count_follow_the_same_rule():
    store = Store(Config())
    store.outlook = _text_outlook(timedelta(hours=40))
    view = SimpleNamespace(store=store, now=NOW, basins=("AL",), states=(), failed=frozenset(), outlook_old=False)
    said = " ".join(outlook_text(view))  # type: ignore[arg-type]
    assert "20%" in said and "70%" not in said
    assert words.area_count(store.outlook, ("AL",), NOW) == 1


def test_the_age_note_and_the_drop_sit_exactly_on_their_thresholds():
    (at_note,) = outlook_areas(_outlook(GIS_NOTE_AFTER), NOW)
    assert at_note.label == "40% in 7 days"  # exactly 12 h: no note yet
    (past_note,) = outlook_areas(_outlook(GIS_NOTE_AFTER + timedelta(seconds=1)), NOW)
    assert past_note.label.endswith("old")
    assert len(outlook_areas(_outlook(GIS_DROP_AFTER), NOW)) == 1  # exactly 24 h: still drawn
    assert outlook_areas(_outlook(GIS_DROP_AFTER + timedelta(seconds=1)), NOW) == ()


async def test_the_series_of_a_storm_that_cleared_is_pruned_though_the_tides_feed_is_off():
    poller, _source, store, clock, _ = build(config=Config(watchlist=WatchlistConfig(ndbc=(), coops=())))
    clock.set(NOW)
    store.tide_series["8000001"] = _tide("8000001", timedelta(minutes=6))
    store.tide_errors["8000001"] = "boom"
    assert not poller.active(protocol.TIDES)
    await poller.tick()
    assert store.tide_series == {} and store.tide_errors == {}


async def test_an_open_gauge_page_keeps_a_silent_series_but_others_expire():
    poller, source, store, clock, _ = build()
    clock.set(NOW)
    source.tide_stations = (gauge("8000001", 25.5, -75.5), gauge("8000002", 25.6, -75.6))
    store.apply_tide_stations(source.tide_stations)
    old = tides.DROP_AFTER + timedelta(hours=1)
    poller.extra_gauges.add("8000001")
    store.tide_series["8000001"] = _tide("8000001", old)
    store.tide_series["8000002"] = _tide("8000002", old)
    store.prune_tides({"8000001", "8000002"}, NOW, {"8000001"})
    assert set(store.tide_series) == {"8000001"}


def test_a_series_with_no_level_is_kept_and_open_pages_come_first_under_the_cap():
    store = Store(Config())
    store.tide_series["8000001"] = TideSeries("8000001", "MLLW")
    store.prune_tides({"8000001"}, NOW)
    assert "8000001" in store.tide_series


async def test_open_gauge_pages_take_the_cap_before_the_storms_gauges():
    from eyewall.poll import MAX_TIDE_GAUGES

    poller, source, store, _clock, _ = build()
    source.tide_stations = tuple(gauge(f"80000{n:02d}", 25.0 + n / 10, -75.0) for n in range(MAX_TIDE_GAUGES + 3))
    store.apply_tide_stations(source.tide_stations)
    source.set_storm("1")
    source.texts["1"] = advisories("1")
    poller.extra_gauges.update(f"80000{n:02d}" for n in range(MAX_TIDE_GAUGES + 2, MAX_TIDE_GAUGES - 1, -1))
    await poller.tick()
    wanted = poller._wanted_gauges()
    assert len(wanted) <= MAX_TIDE_GAUGES
    assert {f"80000{n:02d}" for n in range(MAX_TIDE_GAUGES, MAX_TIDE_GAUGES + 3)} <= set(wanted)


def test_the_poller_and_the_screens_read_one_clock():
    poller, source, *_ = build()
    assert poller.source is source and poller.source.now() == source.now()
