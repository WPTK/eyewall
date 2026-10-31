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
