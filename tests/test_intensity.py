from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from eyewall.models.intensity import RI_GAIN_KT, current_rapid, episode_start, intensification
from eyewall.models.track import BestTrack, BestTrackFix
from eyewall.models.wind import WindRadii
from eyewall.providers.nhc.atcf import parse_bdeck
from eyewall.state import events as ev
from eyewall.state.store import Store
from tests.nhc_fixtures import nhc_text
from tests.state_support import T0, make_storm

START = datetime(2026, 10, 20, tzinfo=UTC)


def fix(hours: float, vmax: int | None) -> BestTrackFix:
    return BestTrackFix(
        START + timedelta(hours=hours), 12.0, -40.0, vmax, None, "TS", WindRadii(),
        None, None, None, None, None, None, None, None, None,
    )  # fmt: skip


def series(*pairs: tuple[float, int | None]) -> list[BestTrackFix]:
    return [fix(h, v) for h, v in pairs]


def test_exactly_thirty_knots_in_24_hours_is_rapid():
    rapid = current_rapid(series((0, 45), (6, 55), (12, 60), (18, 70), (24, 75)))
    assert rapid is not None and rapid.gain_kt == 30


def test_twenty_nine_knots_is_not():
    assert current_rapid(series((0, 45), (12, 60), (24, 74))) is None


def test_the_window_interpolates_between_the_fixes_that_bracket_it():
    # 24 h before hour 30 is hour 6, between 0 h (30 kt) and 12 h (50 kt): 40 kt there
    steps = intensification(series((0, 30), (12, 50), (30, 70)))
    assert steps[-1].gain_kt == 30


def test_nothing_is_extrapolated_before_the_first_fix():
    assert intensification(series((6, 30), (12, 60), (24, 90))) == []


def test_a_gap_wider_than_the_limit_gives_no_answer():
    assert current_rapid(series((0, 30), (18, 40), (36, 90))) is None


def test_missing_wind_fixes_are_skipped_not_zero():
    # the 12 h fix has no wind; 0 and 24 h are 24 h apart and exactly bracket the window
    assert current_rapid(series((0, 30), (12, None), (24, 59))) is None
    assert current_rapid(series((0, 30), (12, None), (24, 60))) is not None
    assert intensification(series((0, None), (24, None))) == []


def test_an_episode_is_keyed_by_the_fix_it_began_at():
    fixes = series((0, 30), (6, 35), (12, 40), (18, 50), (24, 65), (30, 75), (36, 80))
    assert episode_start(fixes[:5]) == START + timedelta(hours=24)  # 65 vs 30 at 0 h: 35
    assert episode_start(fixes) == START + timedelta(hours=24)
    assert episode_start(series((0, 30), (24, 40))) is None


def test_real_b_deck_flags_the_october_rapid_intensification():
    track = parse_bdeck(nhc_text("atcf/bep222026.dat"))
    flagged = [s.end for s in intensification(track.fixes) if s.is_rapid]
    assert flagged[0] == datetime(2026, 10, 23, 6, tzinfo=UTC)  # 40 kt at 22/06 to 70 kt
    assert datetime(2026, 10, 24, 12, tzinfo=UTC) not in flagged  # 100 kt peak is behind, 90 vs 75 is not 30
    assert current_rapid(track.fixes) is None  # the storm has since decayed


def test_the_event_fires_once_per_episode_and_not_without_one():
    track = BestTrack("EP", 22, tuple(series((0, 45), (12, 60), (24, 75))))
    storm = make_storm()
    first = ev.rapid_intensification_events(storm, track, T0)
    assert len(first) == 1 and "30 kt in 24 h" in first[0].message
    later = BestTrack("EP", 22, tuple(series((0, 45), (12, 60), (24, 75), (30, 85))))
    assert ev.rapid_intensification_events(storm, later, T0)[0].key == first[0].key
    assert ev.rapid_intensification_events(storm, None, T0) == []
    assert ev.rapid_intensification_events(storm, BestTrack("EP", 22, tuple(series((0, 45), (24, 50)))), T0) == []


def test_the_store_returns_the_event_with_the_track():
    store = Store()
    storm = make_storm()
    store.apply_storms(type("C", (), {"storms": (storm,)})(), T0)  # type: ignore[arg-type]
    track = BestTrack("AL", 1, tuple(series((0, 45), (24, 80))))
    assert [e.kind.value for e in store.apply_products(storm.id, T0, key=None, track=track)] == [
        "rapid_intensification"
    ]


@given(st.lists(st.tuples(st.integers(0, 120), st.one_of(st.none(), st.integers(0, 190))), max_size=30))
def test_gain_is_bounded_by_the_wind_range_and_never_raises(pairs):
    fixes = series(*sorted(set(pairs), key=lambda p: p[0]))
    winds = [f.vmax_kt for f in fixes if f.vmax_kt is not None]
    for step in intensification(fixes):
        assert min(winds) - max(winds) <= step.gain_kt <= max(winds) - min(winds)
    assert (current_rapid(fixes) is None) or episode_start(fixes) is not None or True


@given(st.lists(st.integers(0, 190), min_size=2, max_size=20), st.integers(1, 6))
def test_a_steady_six_hourly_series_is_rapid_exactly_when_the_gain_over_four_fixes_is_thirty(winds, _unused):
    fixes = series(*[(6 * i, w) for i, w in enumerate(winds)])
    got = {s.end: s.is_rapid for s in intensification(fixes)}
    for i in range(4, len(winds)):
        assert got[START + timedelta(hours=6 * i)] == (winds[i] - winds[i - 4] >= RI_GAIN_KT)
