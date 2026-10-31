"""The poller on a virtual clock: intervals, backoff, away mode, change-triggered refetch and the gated fallback."""

from datetime import timedelta

import pytest

from eyewall.clock import VirtualClock
from eyewall.config import Config, PollConfig
from eyewall.models.storm import CurrentStorms
from eyewall.poll import FALLBACK_ATTEMPTS, FreshnessState, Poller, no_sleep
from eyewall.sources import protocol
from eyewall.state.alerts import AlertEngine
from eyewall.state.store import Store
from tests.state_support import T0, FakeSource, advisories, area, gauge, obs, series, station


def build(source=None, config=None, **kw):
    clock = VirtualClock(T0)
    source = source or FakeSource(clock)
    source.clock = clock
    config = config or Config()
    store = Store(config)
    got = []
    poller = Poller(
        source, store, AlertEngine(config.alerts), config.poll, clock=clock, sleep=no_sleep, on_events=got.extend, **kw
    )
    return poller, source, store, clock, got


async def step(poller, clock, seconds):
    clock.advance(seconds)
    return await poller.tick()


# ---- intervals ----------------------------------------------------------------------------------------------------


async def test_every_feed_with_something_to_do_is_polled_at_the_first_tick_and_then_on_its_own_interval():
    poller, source, _store, clock, _ = build()
    source.set_storm("1")
    source.texts["1"] = advisories("1")
    first = await poller.tick()
    assert [r.feed for r in first] == list(protocol.FEEDS)  # the Bahamas count as a US threat
    assert await step(poller, clock, 299) == []
    assert [r.feed for r in await step(poller, clock, 1)] == [protocol.STORMS, protocol.ALERTS]
    assert source.count("outlook") == 1
    await step(poller, clock, 300)  # 600 s: storms and buoys (600 s) are due; tides (360 s) and satellite (600 s) too
    assert source.count("ndbc_latest") == 2


async def test_alerts_are_polled_only_while_a_storm_threatens_the_us():
    poller, source, _store, clock, _ = build()
    source.set_storm("1", lat=14.0, lon=-40.0)  # mid-Atlantic
    source.texts["1"] = advisories("1")
    await poller.tick()
    assert source.count("alerts") == 0
    source.set_storm("2", lat=26.0, lon=-80.0)  # off Florida
    source.texts["2"] = advisories("2")
    await step(poller, clock, 300)
    assert source.count("alerts") == 1


# ---- freshness and backoff ----------------------------------------------------------------------------------------


async def test_a_failing_feed_backs_off_exponentially_up_to_the_cap_and_never_below_its_interval():
    config = Config(poll=PollConfig(storms=100.0, backoff_max=500.0))
    poller, source, _, clock, _ = build(config=config)
    source.fail.add("storms")
    delays = []
    for _ in range(5):
        await poller.tick()
        delays.append(poller.delay(protocol.STORMS))
        clock.advance(poller.delay(protocol.STORMS))
    assert delays == [200.0, 400.0, 500.0, 500.0, 500.0]
    assert poller.freshness(protocol.STORMS).state is FreshnessState.ERROR
    source.fail.clear()
    await poller.tick()
    assert poller.delay(protocol.STORMS) == 100.0
    assert poller.freshness(protocol.STORMS).state is FreshnessState.FRESH


async def test_the_poll_loop_survives_a_feed_that_raises_and_keeps_the_last_data():
    poller, source, store, clock, _ = build()
    source.set_storm("1")
    source.texts["1"] = advisories("1")
    await poller.tick()
    source.fail.add("storms")
    result = await step(poller, clock, 300)
    assert not result[0].ok
    assert "al012026" in store.storms


async def test_freshness_goes_stale_after_two_and_a_half_intervals_without_a_poll():
    poller, _source, _, clock, _ = build()
    assert poller.freshness(protocol.STORMS).state is FreshnessState.LOADING
    await poller.tick()
    assert poller.freshness(protocol.STORMS).state is FreshnessState.FRESH
    clock.advance(749)
    assert poller.freshness(protocol.STORMS).state is FreshnessState.FRESH
    clock.advance(2)
    assert poller.freshness(protocol.STORMS).state is FreshnessState.STALE


async def test_an_answer_served_from_the_disk_cache_marks_the_feed_stale():
    poller, source, _, _, _ = build()
    source.cached.add(protocol.STORMS)
    await poller.tick()
    fresh = poller.freshness(protocol.STORMS)
    assert fresh.state is FreshnessState.STALE
    assert fresh.from_cache
    assert fresh.data_old


# ---- away mode and refresh ----------------------------------------------------------------------------------------


async def test_away_mode_triples_every_interval_and_coming_back_polls_at_once():
    poller, source, _, clock, _ = build()
    await poller.tick()
    poller.set_away(True)
    assert poller.interval(protocol.STORMS) == 900.0
    assert poller.freshness(protocol.STORMS).stale_after == 2.5 * 900.0
    await step(poller, clock, 300)
    assert source.count("storms") == 2
    await step(poller, clock, 300)  # the next storms poll was scheduled with the away interval
    assert source.count("storms") == 2
    poller.set_away(False)
    assert next(r.feed for r in await poller.tick()) == protocol.STORMS
    assert source.count("storms") == 3


async def test_presence_follows_the_idle_time():
    idle = [10.0]
    poller, *_ = build(idle_for=lambda: idle[0])
    assert poller.observe_presence() is False and not poller.away
    idle[0] = 301.0
    poller.observe_presence()
    assert poller.away
    idle[0] = 1.0
    assert poller.observe_presence() is True
    assert not poller.away


async def test_refresh_makes_every_feed_due():
    poller, _source, _, _clock, _ = build()
    await poller.tick()
    assert poller.due() == []
    poller.refresh()
    assert protocol.STORMS in poller.due()
    assert protocol.OUTLOOK in poller.due()


# ---- change-triggered refetch -------------------------------------------------------------------------------------


async def test_heavy_products_are_fetched_only_when_the_advisory_changes():
    poller, source, _store, clock, _got = build()
    source.set_storm("1")
    source.texts["1"] = advisories("1")
    await poller.tick()
    assert (source.count("advisory"), source.count("forecast_gis"), source.count("track")) == (1, 1, 1)
    for _ in range(3):  # three more polls of the same advisory
        await step(poller, clock, 300)
    assert source.count("storms") == 4
    assert (source.count("advisory"), source.count("forecast_gis"), source.count("graphics")) == (1, 1, 1)
    source.set_storm("2")
    source.texts["2"] = advisories("2")
    await step(poller, clock, 300)
    assert (source.count("advisory"), source.count("forecast_gis"), source.count("graphics")) == (2, 2, 2)


async def test_a_new_last_update_alone_refetches_too():
    poller, source, _, clock, _ = build()
    source.set_storm("1")
    source.texts["1"] = advisories("1")
    await poller.tick()
    source.set_storm("1", updated=T0 + timedelta(minutes=30))
    await step(poller, clock, 300)
    assert source.count("advisory") == 2


async def test_an_intermediate_advisory_refetches_and_is_reported():
    poller, source, _, clock, got = build()
    source.set_storm("3")
    source.texts["3"] = advisories("3")
    await poller.tick()
    source.set_storm("3A", intermediate_only=True)
    source.texts["3A"] = advisories("3A")
    await step(poller, clock, 300)
    assert any("advisory 3A" in e.message for e in got)


async def test_watch_and_warning_changes_between_advisories_are_events():
    poller, source, _, clock, got = build()
    source.set_storm("1")
    source.texts["1"] = advisories("1", area("Tropical Storm Watch", "Keys"))
    await poller.tick()
    source.set_storm("2")
    source.texts["2"] = advisories("2", area("Tropical Storm Warning", "Keys"))
    await step(poller, clock, 300)
    assert {e.kind.value for e in got} >= {"ww_issued", "ww_discontinued"}


async def test_the_api_fallback_is_asked_only_after_tgftp_lags_and_at_most_a_few_times():
    poller, source, store, clock, _ = build()
    source.set_storm("1")
    source.texts["1"] = advisories("1")
    await poller.tick()
    source.set_storm("2")  # tgftp still has nothing for advisory 2
    await step(poller, clock, 300)
    assert (source.count("advisory"), source.count("advisory-fallback")) == (2, 0)
    assert store.storms["al012026"].fetched_key[0] == "1"  # not recorded as fetched: it will be tried again
    source.fallback_texts["2"] = advisories("2")
    await step(poller, clock, 300)
    assert source.count("advisory-fallback") == 1
    assert store.storms["al012026"].fetched_key[0] == "2"
    await step(poller, clock, 300)
    assert source.count("advisory-fallback") == 1  # settled: no more asks


async def test_a_storm_nobody_can_fetch_text_for_stops_being_retried():
    poller, source, store, clock, _ = build()
    source.set_storm("1")
    for _ in range(FALLBACK_ATTEMPTS + 3):
        await step(poller, clock, 300)
    assert source.count("advisory") + source.count("advisory-fallback") == FALLBACK_ATTEMPTS
    assert store.storms["al012026"].fetched_key is not None


# ---- stations -----------------------------------------------------------------------------------------------------


async def test_buoy_series_are_fetched_for_nearby_stations_and_a_crossing_becomes_an_event():
    poller, source, _store, _clock, got = build()
    source.stations = (station("41047", 26.0, -75.5), station("99999", -40.0, 10.0))
    source.buoy_series["41047"] = series("41047", obs(T0 - timedelta(minutes=10), 40))
    source.set_storm("1")
    source.texts["1"] = advisories("1")
    await poller.tick()
    assert source.count("series:41047") == 1
    assert source.count("series:99999") == 0
    assert any(e.kind.value == "buoy_threshold" for e in got)


async def test_each_tide_gauge_gets_its_datum_and_one_that_answers_400_does_not_stop_the_others():
    poller, source, store, _clock, _ = build()
    source.tide_stations = (
        gauge("8000001", 25.5, -75.5),
        gauge("9000002", 25.6, -75.6, great_lakes=True),
        gauge("8000003", 25.7, -75.7),
    )
    source.bad_datum = {"8000001"}
    source.set_storm("1")
    source.texts["1"] = advisories("1")
    await poller.tick()
    assert dict(source.datums) == {"8000001": "MLLW", "9000002": "IGLD", "8000003": "MLLW"}
    assert set(store.tide_series) == {"9000002", "8000003"}
    assert "8000001" in store.tide_errors
    assert poller.freshness(protocol.TIDES).state is FreshnessState.FRESH


async def test_a_quiet_basin_polls_only_storms_and_outlook():
    poller, source, *_ = build()
    source.current = CurrentStorms()
    assert [r.feed for r in await poller.tick()] == [protocol.STORMS, protocol.OUTLOOK]


@pytest.mark.parametrize("away", [False, True])
async def test_seconds_until_next_counts_down_with_the_clock(away):
    poller, _, _, clock, _ = build()
    await poller.tick()
    poller.set_away(away)
    clock.advance(100)
    assert poller.seconds_until_next() is not None
