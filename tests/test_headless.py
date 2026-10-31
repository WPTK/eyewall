"""The headless replay end to end, the store helpers and the new command line flags."""

from datetime import UTC, datetime, timedelta

import pytest

from eyewall.cli import main
from eyewall.config import Config
from eyewall.headless import UntilError, parse_until, run_replay
from eyewall.models.advisory import AdvisorySet
from eyewall.models.forecast import ForecastAdvisory
from eyewall.sources import bundle
from eyewall.sources.replay import ReplaySource
from eyewall.state.store import Store, StormState, track_fixes
from tests.state_support import T0, make_storm, obs, series

START = datetime(2025, 8, 19, 3, tzinfo=UTC)


def demo_source() -> ReplaySource:
    return ReplaySource(bundle.resolve_bundle(bundle.DEMO))


async def test_the_erin_replay_logs_its_advisory_watch_warning_and_buoy_events(tmp_path):
    result = await run_replay(demo_source(), Config(), tmp_path, "+12h")
    kinds = [e.kind.value for e in result.events]
    advisories = [e.adv_num for e in result.events if e.kind.value == "new_advisory"]
    assert advisories == ["31", "31A", "32", "32A", "33"]
    assert kinds.count("new_storm") == 1
    assert {"ww_issued", "ww_changed", "ww_discontinued", "new_discussion"} <= set(kinds)
    surge = next(e for e in result.events if e.kind.value == "ww_issued")
    assert "Storm Surge Warning" in surge.message
    assert surge.adv_num == "33"
    buoy = next(e for e in result.events if e.kind.value == "buoy_threshold")
    assert buoy.subject == "41047:34"
    assert result.ended == START + timedelta(hours=12)


async def test_a_second_run_on_the_same_state_logs_nothing_again(tmp_path):
    first = await run_replay(demo_source(), Config(), tmp_path, "+12h")
    second = await run_replay(demo_source(), Config(), tmp_path, "+12h")
    assert first.events
    assert second.events == []
    assert second.polls == first.polls


async def test_a_different_state_directory_reports_them_again(tmp_path):
    a = await run_replay(demo_source(), Config(), tmp_path / "a", "+4h")
    b = await run_replay(demo_source(), Config(), tmp_path / "b", "+4h")
    assert [e.key for e in a.events] == [e.key for e in b.events]


def test_until_accepts_offsets_and_timestamps():
    assert parse_until("+12h", START) == START + timedelta(hours=12)
    assert parse_until("+90m", START) == START + timedelta(minutes=90)
    assert parse_until("+2d", START) == START + timedelta(days=2)
    assert parse_until("2025-08-20T00:00", START) == datetime(2025, 8, 20, tzinfo=UTC)
    with pytest.raises(UntilError):
        parse_until("tomorrow", START)


def test_the_cli_runs_the_demo_headless_and_prints_events(tmp_path, capsys):
    assert main(["--demo", "--headless", "--until", "+4h", "--state-dir", str(tmp_path), "--no-config"]) == 0
    out = capsys.readouterr()
    assert "new_storm" in out.out
    assert "event(s)" in out.err
    assert main(["--replay", "demo", "--headless", "--until", "+4h", "--state-dir", str(tmp_path), "--no-config"]) == 0
    assert capsys.readouterr().out == ""


def test_the_cli_reports_a_bad_bundle_or_until(tmp_path, capsys):
    assert main(["--replay", str(tmp_path), "--headless", "--no-config", "--state-dir", str(tmp_path)]) == 2
    assert main(["--demo", "--headless", "--until", "soon", "--no-config", "--state-dir", str(tmp_path)]) == 2
    assert "eyewall:" in capsys.readouterr().err


# ---- the store ----------------------------------------------------------------------------------------------------


async def test_track_fixes_count_hours_from_the_center_not_from_the_synoptic_time():
    source = demo_source()
    source.clock.set(datetime(2025, 8, 19, 9, 5, tzinfo=UTC))
    storm = (await source.storms()).storms[0]
    advisories = await source.advisory(storm)
    tcm = advisories.forecast
    assert isinstance(tcm, ForecastAdvisory)
    fixes = track_fixes(StormState(storm, advisories))
    first = next(f for f in tcm.fixes if f.tau == 12)
    assert tcm.issued - tcm.synoptic == timedelta(hours=3)
    expected = (first.valid - tcm.issued).total_seconds() / 3600
    assert expected == 9.0  # tau 12 minus the 3 hour offset
    assert fixes[0].hours == pytest.approx(expected)
    assert track_fixes(StormState(storm, AdvisorySet())) == []


def test_a_stale_pressure_tendency_is_not_shown():
    store = Store()
    store.apply_series(
        series("41001", obs(T0 - timedelta(hours=3), pressure=1000.0), obs(T0 - timedelta(minutes=10), pressure=996.0))
    )
    tendency = store.tendency("41001", T0)
    assert tendency is not None and tendency.delta_hpa == pytest.approx(-4.0)
    assert store.tendency("41001", T0 + timedelta(hours=3)) is None
    assert store.tendency("00000", T0) is None


def test_a_storm_in_a_disabled_basin_is_ignored():
    from eyewall.config import BasinsConfig
    from eyewall.models.storm import CurrentStorms

    store = Store(Config(basins=BasinsConfig(enabled=("EP",))))
    assert store.apply_storms(CurrentStorms((make_storm("1"),)), T0) == []
    assert store.storms == {}


def test_a_replay_never_touches_the_user_seen_file_unless_asked(tmp_path, monkeypatch, capsys):
    import eyewall.state.alerts as alerts

    def refuse() -> None:
        raise AssertionError("a replay must not look for the user state directory")

    monkeypatch.setattr(alerts, "default_state_dir", refuse)
    assert main(["--demo", "--headless", "--until", "+4h", "--no-config"]) == 0
    first = capsys.readouterr().out
    assert main(["--demo", "--headless", "--until", "+4h", "--no-config"]) == 0
    assert capsys.readouterr().out == first  # nothing was remembered between the two runs


def test_pressure_tendency_freshness_follows_the_newest_row_with_a_pressure():
    store = Store()
    # The newest row is fresh but has no pressure; the newest pressure is hours old, so no tendency is shown.
    store.apply_series(
        series(
            "41001",
            obs(T0 - timedelta(hours=6), pressure=1000.0),
            obs(T0 - timedelta(hours=3, minutes=10), pressure=1000.0),
            obs(T0 - timedelta(hours=3), pressure=996.0),
            obs(T0 - timedelta(minutes=5), wind_kt=20),
        )
    )
    assert store.tendency("41001", T0) is None
    store.apply_series(series("41001", obs(T0 - timedelta(hours=3), pressure=1000.0), obs(T0, pressure=997.0)))
    assert store.tendency("41001", T0) is not None


async def _demo_state(times: int):
    from eyewall.models.storm import CurrentStorms

    source = demo_source()
    moments = source.advisory_times()
    store = Store()
    source.clock.set(moments[times])
    storm = (await source.storms()).storms[0]
    store.apply_storms(CurrentStorms((storm,)), moments[times])
    return source, moments, store, storm


async def test_stepping_back_shows_the_older_advisory_without_events_or_newer_products():
    source, moments, store, storm = await _demo_state(-1)
    newer = await source.advisory(storm)
    store.apply_products(storm.id, moments[-1], key=("n", None), advisories=newer)
    source.clock.set(moments[2])
    older = await source.advisory((await source.storms()).storms[0])
    assert older != newer
    events = store.apply_products(storm.id, moments[2], key=("o", None), advisories=older)
    assert events == []
    assert store.storms[storm.id].advisories == older


async def test_a_newer_advisory_still_keeps_a_product_that_did_not_come_back():
    source, moments, store, storm = await _demo_state(2)
    first = await source.advisory(storm)
    store.apply_products(storm.id, moments[2], key=("1", None), advisories=first)
    source.clock.set(moments[3])
    second = await source.advisory((await source.storms()).storms[0])
    partial = AdvisorySet(public=second.public)
    store.apply_products(storm.id, moments[3], key=("2", None), advisories=partial)
    kept = store.storms[storm.id].advisories
    assert kept.public == second.public and kept.forecast == (second.forecast or first.forecast)


async def test_live_headless_polls_a_feed_that_is_due_now_without_waiting_an_interval(monkeypatch):
    import asyncio

    from eyewall import headless

    now = datetime(2026, 1, 1, tzinfo=UTC)
    waits = iter([0.0, 10_000_000.0])
    slept: list[float] = []

    class FakeSource:
        def now(self):
            return now

        async def aclose(self):
            return None

    class FakePoller:
        def __init__(self, *args, **kwargs):
            pass

        async def tick(self):
            return []

        def seconds_until_next(self):
            return next(waits)

        def interval(self, feed):
            return 600.0

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(headless, "LiveSource", FakeSource)
    monkeypatch.setattr(headless, "Poller", FakePoller)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    result = await headless.run_live(Config(), None, "+30m")
    assert slept == [0.0] and result.polls == 2


def _copy_demo(tmp_path):
    import shutil

    target = tmp_path / "bundle"
    shutil.copytree(bundle.demo_bundle_path(), target)
    return target


@pytest.mark.parametrize(
    "storm_id", ["../../etc", "al05/2025", "al05\\2025", "..", "", "al05", "al052025/../x", "xx052025"]
)
def test_a_storm_id_that_is_not_a_storm_id_is_refused_before_it_names_a_folder(tmp_path, storm_id):
    target = _copy_demo(tmp_path)
    manifest = bundle.read_manifest(target)
    (target / bundle.MANIFEST).write_text(
        (target / bundle.MANIFEST)
        .read_text(encoding="utf-8")
        .replace(f'storm_id = "{manifest.storm_id}"', f'storm_id = "{storm_id}"'.replace("\\", "\\\\")),
        encoding="utf-8",
    )
    with pytest.raises(bundle.BundleError, match="storm_id"):
        ReplaySource(target)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("format = 1", 'format = "x"'),
        ("format = 1", "format = [1]"),
        ("graphics = [", "graphics = 5\nold = ["),
        ('{ file = "cone_033.png",', "{ nofile = 1,"),
        ("start = 2025-08-19 03:00:00+00:00", 'start = "soon"'),
    ],
)
def test_a_malformed_manifest_is_a_bundle_error_not_a_traceback(tmp_path, old, new):
    target = _copy_demo(tmp_path)
    text = (target / bundle.MANIFEST).read_text(encoding="utf-8")
    assert old in text
    (target / bundle.MANIFEST).write_text(text.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(bundle.BundleError):
        ReplaySource(target)


def test_the_cli_reports_a_malformed_bundle_with_exit_code_2_and_no_traceback(tmp_path, capsys):
    target = _copy_demo(tmp_path)
    (target / bundle.MANIFEST).write_text('format = "x"\nname = "n"\n', encoding="utf-8")
    code = main(["--replay", str(target), "--headless", "--no-config", "--state-dir", str(tmp_path / "s")])
    err = capsys.readouterr().err
    assert code == 2 and err.startswith("eyewall:") and "Traceback" not in err


def test_unreadable_recorded_files_are_a_bundle_error(tmp_path, monkeypatch):
    target = _copy_demo(tmp_path)
    monkeypatch.setattr(ReplaySource, "_load_stations", lambda self: (_ for _ in ()).throw(ValueError("bad xml")))
    with pytest.raises(bundle.BundleError, match="could not be read"):
        ReplaySource(target)


async def test_a_partial_refetch_keeps_the_stored_public_advisory():
    source, moments, store, storm = await _demo_state(2)
    for moment in moments:  # find a moment where an intermediate public advisory is the newest
        source.clock.set(moment)
        full = await source.advisory((await source.storms()).storms[0])
        if full.forecast and full.public and full.public.issued > full.forecast.issued:
            break
    else:
        pytest.fail("the demo has no intermediate advisory")
    store.apply_products(storm.id, moment, key=("1", None), advisories=full)
    store.apply_products(storm.id, moment, key=("2", None), advisories=AdvisorySet(forecast=full.forecast))
    assert store.storms[storm.id].advisories.public == full.public


async def test_a_newer_set_whose_newest_product_predates_a_stored_intermediate_still_raises_events():
    from eyewall.state.events import EventKind

    source, moments, store, storm = await _demo_state(2)
    source.clock.set(moments[2])
    stored = await source.advisory((await source.storms()).storms[0])
    source.clock.set(moments[-1])
    late = await source.advisory((await source.storms()).storms[0])
    assert late.discussion is not None and stored.discussion is not None
    assert late.discussion.adv_num != stored.discussion.adv_num
    store.apply_products(storm.id, moments[2], key=("1", None), advisories=stored)
    # the public advisory lags (same one as stored) while the forecast and discussion are newer
    mixed = AdvisorySet(forecast=late.forecast, public=stored.public, discussion=late.discussion)
    events = store.apply_products(storm.id, moments[-1], key=("2", None), advisories=mixed)
    assert EventKind.NEW_DISCUSSION in {e.kind for e in events}
    assert store.storms[storm.id].advisories.discussion == late.discussion


def test_a_replay_never_reads_a_file_outside_its_bundle(tmp_path):
    import shutil

    source = demo_source()
    shutil.copytree(source.directory, tmp_path / "bundle")
    (tmp_path / "outside.json").write_text("{}", encoding="utf-8")
    source.directory = tmp_path / "bundle"
    assert source._read("../outside.json") is None
    assert source._read("manifest.toml") is not None
