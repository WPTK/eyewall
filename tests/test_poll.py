"""The poller on a virtual clock: intervals, backoff, away mode, change-triggered refetch and the gated fallback."""

from datetime import timedelta

import pytest

from eyewall.clock import VirtualClock
from eyewall.config import Config, PollConfig, WatchlistConfig
from eyewall.models.advisory import AdvisorySet
from eyewall.models.storm import CurrentStorms
from eyewall.models.watches import AlertsResult
from eyewall.poll import FALLBACK_ATTEMPTS, RETURN_STAGGER_SECONDS, FreshnessState, Poller, no_sleep
from eyewall.sources import protocol
from eyewall.state.alerts import AlertEngine
from eyewall.state.store import Store
from tests.state_support import T0, FakeSource, advisories, area, gauge, make_public, obs, series, station


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


async def test_away_mode_triples_every_interval_and_coming_back_polls_storms_first():
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


async def test_coming_back_from_away_spreads_the_first_polls_out_in_feed_order():
    poller, source, _store, clock, _ = build()
    source.set_storm("1")
    source.texts["1"] = advisories("1")
    await poller.tick()
    poller.set_away(True)
    clock.advance(10)  # nothing is due yet
    poller.set_away(False)
    assert [r.feed for r in await poller.tick()] == [protocol.STORMS]  # storms now, the rest on their own seconds
    seen = [protocol.STORMS]
    for _ in protocol.FEEDS[1:]:
        clock.advance(RETURN_STAGGER_SECONDS)
        seen += [r.feed for r in await poller.tick()]
    assert seen == [f for f in protocol.FEEDS if poller._enabled(f)]
    assert source.count("storms") == 2


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


async def test_a_quiet_basin_with_no_watchlist_polls_only_storms_and_outlook():
    poller, source, *_ = build(config=Config(watchlist=WatchlistConfig(ndbc=(), coops=())))
    source.current = CurrentStorms()
    assert [r.feed for r in await poller.tick()] == [protocol.STORMS, protocol.OUTLOOK]


async def test_a_quiet_basin_still_polls_the_watchlisted_buoys_and_gauges():
    config = Config(watchlist=WatchlistConfig(ndbc=("41010", "42001"), coops=("8721604",)))
    poller, source, _store, *_ = build(config=config)
    source.current = CurrentStorms()
    source.stations = (station("41010", 28.9, -78.5), station("42001", 25.9, -89.7), station("41002", 32.0, -75.0))
    source.tide_stations = (gauge("8721604", 28.4, -80.6),)
    results = await poller.tick()
    assert [r.feed for r in results] == [protocol.STORMS, protocol.OUTLOOK, protocol.BUOYS, protocol.TIDES]
    # A watchlist-only buoy is read from latest_obs; no series file is fetched for it.
    assert [c for c in source.calls if c.startswith("series:")] == []
    assert source.datums == [("8721604", "MLLW")]
    assert not poller.active(protocol.SATELLITE) and not poller.active(protocol.ALERTS)


async def test_only_the_gauge_side_of_the_watchlist_switches_the_tides_feed_on():
    config = Config(watchlist=WatchlistConfig(ndbc=("41010",), coops=()))
    poller, source, *_ = build(config=config)
    source.current = CurrentStorms()
    assert poller.active(protocol.BUOYS) and not poller.active(protocol.TIDES)


async def test_a_station_an_open_screen_asks_for_is_polled_and_a_changed_watchlist_is_due_at_once():
    config = Config(watchlist=WatchlistConfig(ndbc=(), coops=()))
    poller, source, store, _clock, _ = build(config=config)
    source.current = CurrentStorms()
    source.stations = (station("41002", 32.0, -75.0),)
    await poller.tick()
    assert not poller.active(protocol.BUOYS)
    poller.extra_buoys.add("41002")
    assert poller.active(protocol.BUOYS)
    poller.refresh_feeds(protocol.BUOYS)
    await poller.tick()
    assert "series:41002" in source.calls
    # the watchlist grows: only the buoy feed is made due, the others keep their schedule
    store.config = Config(watchlist=WatchlistConfig(ndbc=("41002",), coops=()))
    poller.extra_buoys.clear()
    before = source.count("ndbc_latest")
    assert await poller.tick() == []
    poller.refresh_feeds(protocol.BUOYS)
    assert [r.feed for r in await poller.tick()] == [protocol.BUOYS]
    assert source.count("ndbc_latest") == before + 1


@pytest.mark.parametrize("away", [False, True])
async def test_seconds_until_next_counts_down_with_the_clock(away):
    poller, _, _, clock, _ = build()
    await poller.tick()
    poller.set_away(away)
    clock.advance(100)
    assert poller.seconds_until_next() is not None


# ---- review fixes -------------------------------------------------------------------------------------------------


async def test_one_lagging_product_is_treated_as_behind_and_does_not_wipe_the_good_data():
    poller, source, store, clock, _ = build()
    source.set_storm("1")
    source.texts["1"] = advisories("1", area("Tropical Storm Warning", "Keys"))
    await poller.tick()
    assert store.us_threat()
    source.set_storm("2")
    full = advisories("2", area("Tropical Storm Warning", "Keys"))
    source.texts["2"] = AdvisorySet(public=full.public, discussion=full.discussion)  # the forecast (TCM) still lags
    await step(poller, clock, 300)
    assert store.storms["al012026"].fetched_key[0] == "1"  # not settled: asked again
    assert store.storms["al012026"].advisories.public.adv_num.number == 1  # type: ignore[union-attr]
    source.fallback_texts["2"] = full  # the second ask goes through api.weather.gov
    await step(poller, clock, 300)
    assert store.storms["al012026"].fetched_key[0] == "2"


async def test_a_product_that_stays_missing_keeps_the_previous_one_and_the_warning_diff_survives():
    poller, source, store, clock, got = build()
    source.set_storm("1")
    source.texts["1"] = advisories("1", area("Tropical Storm Warning", "Keys"))
    await poller.tick()
    old_forecast = store.storms["al012026"].advisories.forecast
    source.set_storm("2")
    full = advisories("2", area("Hurricane Warning", "Keys"))
    source.texts["2"] = AdvisorySet(public=full.public, discussion=full.discussion)
    source.fallback_texts["2"] = source.texts["2"]
    for _ in range(FALLBACK_ATTEMPTS):
        await step(poller, clock, 300)
    state = store.storms["al012026"]
    assert state.advisories.forecast is old_forecast  # kept, not replaced with None
    assert state.advisories.public.adv_num.number == 2  # type: ignore[union-attr]
    assert store.us_threat()
    assert any(e.kind.value == "ww_changed" or e.kind.value == "ww_issued" for e in got)


async def test_store_keeps_the_previous_product_when_the_new_one_is_none():
    _, source, store, _, _ = build()
    source.set_storm("1")
    store.apply_storms(source.current, T0)
    store.apply_products("al012026", T0, key=("1", T0), advisories=advisories("1"))
    store.apply_products("al012026", T0, key=("2", T0), advisories=AdvisorySet(public=make_public("2")))
    kept = store.storms["al012026"].advisories
    assert kept.public.adv_num.number == 2  # type: ignore[union-attr]
    assert kept.forecast is not None and kept.discussion is not None


@pytest.mark.parametrize("product", ["forecast_gis", "radii_gis", "track", "graphics"])
async def test_a_product_that_fails_is_retried_on_the_next_poll_within_the_attempt_cap(product):
    poller, source, store, clock, _ = build()
    source.set_storm("1")
    source.texts["1"] = advisories("1")
    source.fail_products.add(product)
    await poller.tick()
    assert store.storms["al012026"].fetched_key is None  # not settled
    await step(poller, clock, 300)
    assert source.count(product) == 2
    source.fail_products.clear()
    await step(poller, clock, 300)
    assert source.count(product) == 3
    assert store.storms["al012026"].fetched_key[0] == "1"
    await step(poller, clock, 300)
    assert source.count(product) == 3  # settled


async def test_a_product_that_always_fails_stops_being_retried_at_the_cap():
    poller, source, store, clock, _ = build()
    source.set_storm("1")
    source.texts["1"] = advisories("1")
    source.fail_products.add("track")
    for _ in range(FALLBACK_ATTEMPTS + 3):
        await step(poller, clock, 300)
    assert source.count("track") == FALLBACK_ATTEMPTS
    assert store.storms["al012026"].fetched_key is not None


async def test_the_backoff_exponent_is_capped_so_a_long_outage_cannot_overflow():
    poller, source, _, _, _ = build()
    source.fail.add("storms")
    await poller.tick()
    poller._feeds[protocol.STORMS].failures = 5000
    assert poller.delay(protocol.STORMS) == poller.config.backoff_max


async def test_the_alerts_are_cleared_when_the_alerts_feed_turns_off():
    poller, source, store, clock, _ = build()
    source.alert_result = AlertsResult(skipped=2)
    source.set_storm("1", lat=26.0, lon=-80.0)
    source.texts["1"] = advisories("1")
    await poller.tick()
    assert store.alerts.skipped == 2
    source.set_storm("2", lat=14.0, lon=-40.0)  # out to sea: not a US threat any more
    source.texts["2"] = advisories("2")
    await step(poller, clock, 300)
    assert store.alerts == AlertsResult()


async def test_a_listener_that_raises_does_not_stop_the_poll():
    seen = []

    def bad_result(result):
        seen.append(result.feed)
        raise RuntimeError("screen bug")

    def bad_events(events):
        raise RuntimeError("toast bug")

    poller = build(on_result=bad_result)[0]
    poller.on_events = bad_events
    results = await poller.tick()
    assert results
    assert seen


async def test_open_pages_and_storm_buoys_share_one_cap_on_series_files():
    from eyewall.poll import MAX_BUOY_SERIES

    config = Config(watchlist=WatchlistConfig(ndbc=tuple(f"4{n:04d}" for n in range(60)), coops=()))
    poller, source, *_ = build(config=config)
    source.stations = tuple(station(f"4{n:04d}", 30.0 + n / 100, -75.0) for n in range(60))
    await poller.tick()
    fetched = [c for c in source.calls if c.startswith("series:")]
    assert len(fetched) <= MAX_BUOY_SERIES
    poller.extra_buoys.update({"49999", "48888"})
    source.calls.clear()
    poller.refresh_feeds(protocol.BUOYS)
    await poller.tick()
    fetched = [c for c in source.calls if c.startswith("series:")]
    assert len(fetched) <= MAX_BUOY_SERIES
    assert {"series:49999", "series:48888"} <= set(fetched)  # an open page comes before the storm's list


async def test_watchlisted_gauges_share_the_cap_with_a_storms_gauges():
    from eyewall.poll import MAX_TIDE_GAUGES

    ids = [f"87{n:05d}" for n in range(40)]
    config = Config(watchlist=WatchlistConfig(ndbc=(), coops=tuple(ids)))
    poller, source, *_ = build(config=config)
    source.current = CurrentStorms()
    source.tide_stations = tuple(gauge(i, 28.0 + n / 10, -80.0) for n, i in enumerate(ids))
    await poller.tick()
    assert len(source.datums) == MAX_TIDE_GAUGES
