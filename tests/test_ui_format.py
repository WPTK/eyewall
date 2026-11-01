"""Pure helpers behind the interface: coordinate text and the map's fit points."""

from eyewall.ui.adapt import basin_points
from eyewall.ui.products import fmt_lat, fmt_lon


def test_coordinates_carry_hemisphere_letters():
    assert fmt_lat(25.1) == "25.1N"
    assert fmt_lat(-3.0) == "3.0S"
    assert fmt_lon(-75.25) in {"75.2W", "75.3W"}
    assert fmt_lon(170.0) == "170.0E"


def test_basin_points_fit_one_basin_or_all():
    assert len(basin_points(("AL",))) == 2
    assert len(basin_points(())) == len(basin_points(("AL", "EP", "CP")))


def test_status_bar_names_a_source_only_when_it_is_stale_or_failing():
    from eyewall.poll import Freshness, FreshnessState
    from eyewall.sources import protocol
    from eyewall.ui.format import FeedStatus, status_bar
    from eyewall.ui.glyphs import UNICODE

    def bar(*states: tuple[str, FreshnessState]) -> str:
        feeds = [FeedStatus(feed, Freshness(state, age=125.0)) for feed, state in states]
        return status_bar(feeds, next_poll=None, alert_count=0, replay=None, away=False, width=140, g=UNICODE).plain

    fresh = FreshnessState.FRESH
    assert bar((protocol.STORMS, fresh), (protocol.BUOYS, fresh)).strip() == "● sources ok"
    stale = bar(
        (protocol.STORMS, fresh), (protocol.BUOYS, FreshnessState.STALE), (protocol.TIDES, FreshnessState.ERROR)
    )
    assert "buoys 2m05s" in stale and "tides 2m05s" in stale and "storms" not in stale and "sources ok" not in stale
    assert "◐" in stale and "✕" in stale


def test_storm_list_shows_a_header_only_for_a_basin_with_storms():
    from datetime import UTC, datetime

    from eyewall.state.store import Store
    from eyewall.ui.format import build_rows
    from eyewall.ui.glyphs import UNICODE
    from eyewall.units import PRESETS

    store = Store()
    store.storms_loaded = True
    rows = build_rows(store, ("AL", "EP", "CP"), datetime(2026, 1, 1, tzinfo=UTC), PRESETS["nautical"], UNICODE)
    assert [r.kind for r in rows] == ["quiet"]
    assert rows[0].text.plain.strip() == "No tropical cyclones"


def test_status_bar_with_no_active_feeds_says_nothing_green():
    from eyewall.poll import Freshness, FreshnessState
    from eyewall.sources import protocol
    from eyewall.ui.format import FeedStatus, status_bar
    from eyewall.ui.glyphs import UNICODE

    feeds = [FeedStatus(protocol.ALERTS, Freshness(FreshnessState.FRESH), active=False)]
    bar = status_bar(feeds, next_poll=None, alert_count=0, replay=None, away=False, width=140, g=UNICODE)
    assert "sources ok" not in bar.plain


def test_no_connection_needs_storms_never_loaded_and_the_storms_feed_failing():
    from datetime import UTC, datetime

    from eyewall.state.store import Store
    from eyewall.ui.format import build_rows
    from eyewall.ui.glyphs import UNICODE
    from eyewall.units import PRESETS

    now = datetime(2026, 1, 1, tzinfo=UTC)

    def line(*, loaded: bool, unreachable: bool) -> str:
        store = Store()
        store.storms_loaded = loaded
        rows = build_rows(store, ("AL",), now, PRESETS["nautical"], UNICODE, unreachable=unreachable)
        return rows[0].text.plain.strip()

    assert line(loaded=False, unreachable=True) == "no connection"
    assert line(loaded=False, unreachable=False) == "loading..."
    assert (
        line(loaded=True, unreachable=True) == "No tropical cyclones"
    )  # storms answered once; the outage is elsewhere


def test_status_bar_degrades_by_priority_and_never_truncates():
    from datetime import UTC, datetime

    from eyewall.poll import Freshness, FreshnessState
    from eyewall.sources import protocol
    from eyewall.ui.format import FeedStatus, ReplayStatus, status_bar
    from eyewall.ui.glyphs import UNICODE

    feeds = [FeedStatus(protocol.BUOYS, Freshness(FreshnessState.STALE, age=125.0, from_cache=True))]
    replay = ReplayStatus(False, 60, datetime(2025, 8, 20, 6, tzinfo=UTC), "38")

    def bar(width: int) -> str:
        return status_bar(feeds, next_poll=42.0, alert_count=3, replay=replay, away=True, width=width, g=UNICODE).plain

    full = bar(200)
    assert all(word in full for word in ("buoys 2m05s", "OFFLINE", "idle", "next", "adv 38", "Wed 20 Aug"))
    previous = len(full)
    for width in range(120, 0, -1):
        text = bar(width)
        assert len(text) <= max(width, 0) or text == ""
        assert len(text) <= previous  # only ever gets shorter as the room shrinks
        previous = len(text)
    marks = ("replay", "OFFLINE", "buoys", "3 alerts", "idle", "next")  # highest priority first
    for width in range(200, 0, -1):
        present = [mark in bar(width) or (mark == "buoys" and "buo" in bar(width)) for mark in marks]
        assert present == sorted(present, reverse=True), (width, present)  # a lower one is never kept over a higher one
    assert "replay" in bar(30) and "Aug" not in bar(30)  # the replay is the last to go, and shortens first


def test_a_failing_feed_outlasts_the_alert_count_and_a_healthy_one_does_not():
    from eyewall.poll import Freshness, FreshnessState
    from eyewall.sources import protocol
    from eyewall.ui.format import FeedStatus, status_bar
    from eyewall.ui.glyphs import UNICODE

    def bar(state: FreshnessState, width: int) -> str:
        feeds = [FeedStatus(protocol.BUOYS, Freshness(state, age=125.0))]
        return status_bar(feeds, next_poll=42.0, alert_count=3, replay=None, away=False, width=width, g=UNICODE).plain

    assert "next" not in bar(FreshnessState.ERROR, 25) and "buo" in bar(FreshnessState.ERROR, 25)
    assert "3 alerts" in bar(FreshnessState.ERROR, 25)
    assert "buo" in bar(FreshnessState.ERROR, 14) and "3 alerts" not in bar(FreshnessState.ERROR, 14)  # alerts go first
    assert "sources ok" in bar(FreshnessState.FRESH, 25) and "next" not in bar(FreshnessState.FRESH, 25)
    assert "sources ok" not in bar(FreshnessState.FRESH, 12) and "3 alerts" in bar(FreshnessState.FRESH, 12)


def test_the_status_line_names_idle_and_counts_alerts_in_words() -> None:
    from eyewall.ui.format import status_bar
    from eyewall.ui.glyphs import UNICODE

    def bar(count: int, away: bool) -> str:
        return status_bar([], next_poll=None, alert_count=count, replay=None, away=away, width=80, g=UNICODE).plain

    assert "1 alert" in bar(1, False) and "1 alerts" not in bar(1, False)
    assert "9 alerts" in bar(9, False) and "idle" not in bar(9, False)
    assert "idle" in bar(0, True) and "away" not in bar(0, True) and "alert" not in bar(0, True)


def test_the_help_screen_explains_the_status_line_words() -> None:
    from eyewall.ui.screens.help import HELP

    keys = {key: text for _, rows in HELP for key, text in rows}
    assert "alert" in keys["N alerts"] and "idle" in keys
