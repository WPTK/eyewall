"""NOAA answers badly: stale validators, a 304 with nothing to show for it, cut-off and empty bodies, 429 and 5xx runs.

respx plays NOAA under the real `LiveSource` (disk cache, retry loop, clients, parsers) and the real `Poller`. The rule
each test checks is the same: the last good data stays on screen and the feed says it is not current, and an answer with
nothing in it is never read as "there is nothing to report" (audit #183; the empty outlook is #171).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from itertools import chain, repeat
from pathlib import Path

import httpx
import pytest
import respx

from eyewall.clock import VirtualClock
from eyewall.config import Config
from eyewall.poll import FreshnessState, Poller, no_sleep
from eyewall.providers.nhc import ids
from eyewall.sources import protocol
from eyewall.sources.live import LiveSource
from eyewall.state.alerts import AlertEngine
from eyewall.state.store import Store
from tests.nhc_fixtures import nhc_bytes

NOW = datetime(2026, 9, 29, 22, tzinfo=UTC)
STORM = "al062026"
STORMS_URL = ids.CURRENT_STORMS_URL


def current(intensity: int | None = None) -> bytes:
    data = json.loads(nhc_bytes("current/populated.json"))
    data["activeStorms"] = [s for s in data["activeStorms"] if s["id"] == STORM]
    if intensity is not None:
        data["activeStorms"][0]["intensity"] = str(intensity)
    return json.dumps(data).encode()


def sequence(*answers: httpx.Response | Exception):  # type: ignore[no-untyped-def]
    """Each request gets the next answer; the last one repeats."""
    return chain(answers, repeat(answers[-1]))


class CutOff(httpx.AsyncByteStream):
    """A body that stops half way: the connection drops after the first bytes."""

    def __init__(self, body: bytes) -> None:
        self.body = body

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        yield self.body[: len(self.body) // 2]
        raise httpx.ReadError("connection lost")


@pytest.fixture
def noaa():  # type: ignore[no-untyped-def]
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        yield router


def build(router: respx.MockRouter, cache_dir: Path):  # type: ignore[no-untyped-def]
    """The real source and poller over the routes the test set up; every other URL is a 404, as a missing product is."""
    router.route().respond(404)
    clock = VirtualClock(NOW)
    source = LiveSource(cache_dir=cache_dir, clock=clock)
    source.nhc._sleep = no_sleep
    store = Store(Config())
    poller = Poller(source, store, AlertEngine(), Config().poll, clock=clock, sleep=no_sleep)
    return poller, source, store, clock


async def poll(poller: Poller, clock: VirtualClock, seconds: float = 3600) -> None:
    """Let the storms feed come due and poll once."""
    clock.advance(seconds)
    poller.refresh()
    await poller.tick()


def intensity(store: Store) -> int | None:
    return store.storms[STORM].storm.intensity_kt


# ---- validators and the cache --------------------------------------------------------------------------------------


async def test_a_not_modified_answer_returns_the_cached_storm_list(noaa, tmp_path):  # type: ignore[no-untyped-def]
    body = current(60)
    route = noaa.get(STORMS_URL).mock(
        side_effect=sequence(
            httpx.Response(
                200, content=body, headers={"ETag": '"v1"', "Last-Modified": "Tue, 29 Sep 2026 21:00:00 GMT"}
            ),
            httpx.Response(304),
        )
    )
    poller, source, store, clock = build(noaa, tmp_path)
    try:
        await poll(poller, clock, 0)
        await poll(poller, clock)
        second = route.calls[1].request
        assert second.headers["If-None-Match"] == '"v1"'
        assert second.headers["If-Modified-Since"] == "Tue, 29 Sep 2026 21:00:00 GMT"
        assert intensity(store) == 60
        assert poller.freshness(protocol.STORMS).state is FreshnessState.FRESH
    finally:
        await source.aclose()


@pytest.mark.xfail(strict=True, reason="#192: a 304 with no body behind it is read as an empty storm list")
async def test_a_not_modified_answer_nobody_asked_for_is_not_an_empty_storm_list(noaa, tmp_path):  # type: ignore[no-untyped-def]
    """A 304 with no validators sent and nothing cached has no body to go with it. It must not read as 'no storms'."""
    noaa.get(STORMS_URL).mock(side_effect=sequence(httpx.Response(304)))
    poller, source, store, clock = build(noaa, tmp_path)
    try:
        await poll(poller, clock, 0)
        assert not store.storms_loaded, "a 304 with nothing behind it was taken as the first list of storms"
        assert poller.freshness(protocol.STORMS).state is FreshnessState.ERROR
    finally:
        await source.aclose()


async def test_stale_validators_do_not_hide_a_changed_storm_list(noaa, tmp_path):  # type: ignore[no-untyped-def]
    """The server ignores the validators and sends a new body with the old ETag: the new body is what is shown."""
    noaa.get(STORMS_URL).mock(
        side_effect=sequence(
            httpx.Response(200, content=current(60), headers={"ETag": '"v1"'}),
            httpx.Response(200, content=current(100), headers={"ETag": '"v1"'}),
        )
    )
    poller, source, store, clock = build(noaa, tmp_path)
    try:
        await poll(poller, clock, 0)
        await poll(poller, clock)
        assert intensity(store) == 100
    finally:
        await source.aclose()


# ---- bodies that are cut off or hold nothing -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(lambda: httpx.Response(200, stream=CutOff(current(60))), id="cut-off-stream"),
        pytest.param(lambda: httpx.Response(200, content=current(60)[:40]), id="truncated-json"),
        pytest.param(lambda: httpx.Response(204), id="204"),
        pytest.param(lambda: httpx.Response(200, content=b""), id="empty-200"),
        pytest.param(lambda: httpx.Response(200, content=b"null"), id="json-null"),
        pytest.param(lambda: httpx.Response(200, content=b"<html>down for maintenance</html>"), id="maintenance-page"),
    ],
)
async def test_a_bad_storm_list_keeps_the_last_good_one_and_says_the_feed_is_not_current(noaa, tmp_path, answer):  # type: ignore[no-untyped-def]
    noaa.get(STORMS_URL).mock(side_effect=sequence(httpx.Response(200, content=current(60)), answer()))
    poller, source, store, clock = build(noaa, tmp_path)
    try:
        await poll(poller, clock, 0)
        assert intensity(store) == 60
        await poll(poller, clock)
        assert intensity(store) == 60, "the storm vanished from the screen"
        assert poller.freshness(protocol.STORMS).state in (FreshnessState.STALE, FreshnessState.ERROR)
    finally:
        await source.aclose()


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(lambda: httpx.Response(204), id="204"),
        pytest.param(lambda: httpx.Response(200, content=b""), id="empty-200"),
        pytest.param(lambda: httpx.Response(200, stream=CutOff(current(60))), id="cut-off-stream"),
    ],
)
async def test_a_first_poll_with_nothing_in_it_is_a_failure_not_a_quiet_day(noaa, tmp_path, answer):  # type: ignore[no-untyped-def]
    noaa.get(STORMS_URL).mock(side_effect=sequence(answer()))
    poller, source, store, clock = build(noaa, tmp_path)
    try:
        await poll(poller, clock, 0)
        assert not store.storms_loaded, "an empty answer was taken as the first list of storms"
        assert poller.freshness(protocol.STORMS).state is FreshnessState.ERROR
    finally:
        await source.aclose()


@pytest.mark.xfail(strict=True, reason="#171: an empty outlook text is read as 'no outlook'")
async def test_an_empty_outlook_text_is_a_failed_fetch(noaa, tmp_path):  # type: ignore[no-untyped-def]
    for basin in ids.Basin:
        noaa.get(ids.outlook_url(basin)).respond(200, content=b"")
    _, source, _, _ = build(noaa, tmp_path)
    try:
        with pytest.raises(Exception):  # noqa: B017 - any failure; what matters is that it is not an empty outlook
            await source.outlook()
    finally:
        await source.aclose()


# ---- 429 and 5xx ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("retry_after", ["600", None])
async def test_a_429_keeps_the_storms_and_backs_the_feed_off(noaa, tmp_path, retry_after):  # type: ignore[no-untyped-def]
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    noaa.get(STORMS_URL).mock(
        side_effect=sequence(httpx.Response(200, content=current(60)), httpx.Response(429, headers=headers))
    )
    poller, source, store, clock = build(noaa, tmp_path)
    try:
        await poll(poller, clock, 0)
        await poll(poller, clock)
        assert intensity(store) == 60
        state = poller.freshness(protocol.STORMS)
        assert state.state in (FreshnessState.STALE, FreshnessState.ERROR)
        wait = poller._feeds[protocol.STORMS].next_at - clock.monotonic()
        assert wait > 0
        if retry_after is not None:
            assert wait >= min(float(retry_after), 30), "the server's Retry-After was not honoured"
    finally:
        await source.aclose()


async def test_a_run_of_5xx_during_a_fast_changing_storm_never_shows_old_news_as_current(noaa, tmp_path):  # type: ignore[no-untyped-def]
    """Rapid intensification: 50 kt, then three polls that fail, then 115 kt. The screen holds 50 kt and says so until
    the new list arrives, and the new list replaces it."""
    noaa.get(STORMS_URL).mock(
        side_effect=sequence(
            httpx.Response(200, content=current(50), headers={"ETag": '"a"'}),
            httpx.Response(503),
            httpx.Response(502),
            httpx.Response(500),
            httpx.Response(200, content=current(115), headers={"ETag": '"b"'}),
        )
    )
    poller, source, store, clock = build(noaa, tmp_path)
    try:
        await poll(poller, clock, 0)
        assert intensity(store) == 50
        for _ in range(3):
            await poll(poller, clock)
            assert intensity(store) == 50
            assert poller.freshness(protocol.STORMS).state is not FreshnessState.FRESH
        await poll(poller, clock, 7200)
        assert intensity(store) == 115
        assert poller.freshness(protocol.STORMS).state is FreshnessState.FRESH
    finally:
        await source.aclose()
