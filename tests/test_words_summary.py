"""`eyewall --summary`: the same sentences printed once as plain text, from a replay or a live poll."""

import subprocess
import sys
from datetime import timedelta, timezone

import pytest

from eyewall import cli, headless
from eyewall.config import Config
from eyewall.headless import HeadlessResult, run_replay
from eyewall.models.outlook import Outlook
from eyewall.sources import bundle
from eyewall.sources.replay import ReplaySource
from eyewall.state.store import Store
from eyewall.ui.words.summary import _gauge_line, summary_lines
from eyewall.units import PRESETS
from tests.nhc_fixtures import gis_bytes
from tests.state_support import T0

EDT = timezone(timedelta(hours=-4), "EDT")


async def erin(until="+2h"):
    source = ReplaySource(bundle.resolve_bundle(bundle.DEMO))
    return await run_replay(source, Config(), None, until)


async def test_the_replay_summary_reads_the_storm_its_warnings_and_its_buoys():
    result = await erin()
    lines = summary_lines(result.store, PRESETS["us"], result.ended, EDT)
    assert lines[0] == (
        "Hurricane Erin, Category 3, is about 690 mi SW of Bermuda and 780 mi SSE of Cape Hatteras North Carolina "
        "and moving NW at 8 mph."
    )
    assert lines[1] == "Maximum sustained winds are 125 mph."
    assert "Tropical storm conditions are expected in Turks and Caicos Islands and Southeast Bahamas." in lines
    assert any(
        line.startswith("A Tropical Storm Warning means that tropical storm conditions are expected") for line in lines
    )
    assert any(line.startswith("Updated ") and line.endswith(" ago.") for line in lines)
    buoys = [line for line in lines if line.startswith("Buoy ")]
    assert buoys
    assert buoys[0].startswith("Buoy 41047 (NE BAHAMAS")
    assert "Pressure is falling" in buoys[0]
    assert "" in lines  # parts are separated by an empty line


async def test_every_unit_preset_rebuilds_the_summary():
    result = await erin()
    lead = {name: summary_lines(result.store, preset, result.ended, EDT)[0] for name, preset in PRESETS.items()}
    assert "nm SW of Bermuda" in lead["nautical"]
    assert "mi SW of Bermuda" in lead["us"]
    assert "km SW of Bermuda" in lead["metric"]
    assert lead["nautical"].endswith("moving NW at 7 kt.")
    assert lead["metric"].endswith("moving NW at 13 km/h.")


def test_with_no_storm_the_summary_says_so_and_gives_the_outlook():
    from eyewall.providers.nhc.two import parse_gtwo_zip

    store = Store(Config())
    store.outlook = Outlook(gis=parse_gtwo_zip(gis_bytes("gtwo_20250926.zip")))
    assert summary_lines(store, PRESETS["us"], T0, EDT) == [
        "No tropical storms in the Atlantic, East Pacific and Central Pacific right now.",
        "",
        "NHC is watching 1 area: a 90% chance it forms within 7 days, and 80% within 2 days.",
    ]


# ------------------------------------------------------------------------------------------------------ the command


def test_summary_on_a_replay_prints_plain_text_and_exits_zero(capsys, tmp_path):
    assert cli.main(["--no-config", "--demo", "--summary", "--until", "+2h", "--state-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Hurricane Erin, Category 3, is about ")
    assert "\x1b" not in out
    assert out.endswith("\n")
    assert list(tmp_path.iterdir()) == []  # a summary never touches the seen-event set


def test_summary_uses_the_units_of_the_config(capsys, tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[units]\npreset = "metric"\n', encoding="utf-8")
    assert cli.main(["--config", str(path), "--demo", "--summary", "--until", "+2h"]) == 0
    assert " km SW of Bermuda " in capsys.readouterr().out


def test_summary_runs_as_a_program_with_no_terminal_and_no_colour():
    run = subprocess.run(
        [sys.executable, "-m", "eyewall", "--no-config", "--demo", "--summary", "--until", "+2h"],
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
        env={"NO_COLOR": "1", "PATH": "", "SYSTEMROOT": "C:\\Windows"} if sys.platform == "win32" else None,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout.startswith("Hurricane Erin")
    assert "\x1b" not in run.stdout


def test_summary_and_headless_cannot_be_combined():
    with pytest.raises(SystemExit) as raised:
        cli.main(["--demo", "--summary", "--headless"])
    assert raised.value.code == 2


def test_until_still_needs_headless_or_summary():
    with pytest.raises(SystemExit) as raised:
        cli.main(["--demo", "--until", "+1h"])
    assert raised.value.code == 2


@pytest.mark.parametrize(
    "argv", [["--replay", "no-such-bundle", "--summary"], ["--demo", "--summary", "--until", "soon"]]
)
def test_a_bad_bundle_or_until_exits_two(argv, capsys):
    assert cli.main(["--no-config", *argv]) == 2
    assert capsys.readouterr().err.startswith("eyewall: ")


def test_a_live_summary_prints_what_the_poll_found(monkeypatch, capsys):
    async def fake(config, state_dir, until, *, emit=None):
        assert state_dir is None  # never the user's seen set
        return HeadlessResult(store=Store(config), ended=T0, feeds_ok=3)

    monkeypatch.setattr(headless, "run_live", fake)
    assert cli.main(["--no-config", "--summary", "--basin", "AL"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "No tropical storms in the Atlantic right now."


def test_a_live_summary_where_every_feed_failed_exits_one_and_prints_nothing(monkeypatch, capsys):
    async def fake(config, state_dir, until, *, emit=None):
        return HeadlessResult(store=Store(config), ended=T0, feeds_failed=3)

    monkeypatch.setattr(headless, "run_live", fake)
    assert cli.main(["--no-config", "--summary"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "eyewall: every feed failed\n"


async def test_a_failed_storms_feed_says_so_instead_of_reading_as_quiet():
    result = await erin()
    assert summary_lines(result.store, PRESETS["us"], result.ended, EDT, frozenset({"storms"})) == [
        "Storm data unavailable."
    ]


async def test_a_failed_tides_or_buoys_feed_says_unavailable_not_waiting():
    result = await erin()
    store = result.store
    store.series, store.tide_series, store.latest = {}, {}, {}
    quiet = summary_lines(store, PRESETS["us"], result.ended, EDT)
    assert any("Waiting for the first" in line for line in quiet)
    failed = summary_lines(store, PRESETS["us"], result.ended, EDT, frozenset({"buoys", "tides"}))
    assert any("Buoy data unavailable." in line for line in failed)
    assert not any("Waiting for the first" in line for line in failed)
    gauge = store.tide_stations[0]  # the replay has none near Erin, so ask for one directly
    assert _gauge_line(store, gauge, result.ended, PRESETS["us"], frozenset()).endswith(
        "Waiting for the first water level."
    )
    unavailable = _gauge_line(store, gauge, result.ended, PRESETS["us"], frozenset({"tides"}))
    assert unavailable.endswith("Water level data unavailable.")


def test_a_live_summary_without_the_storms_feed_exits_one(monkeypatch, capsys):
    async def fake(config, state_dir, until, *, emit=None):
        return HeadlessResult(store=Store(config), ended=T0, feeds_ok=2, feeds_failed=1, failed_feeds={"storms"})

    monkeypatch.setattr(headless, "run_live", fake)
    assert cli.main(["--no-config", "--summary"]) == 1
    assert capsys.readouterr().out.splitlines() == ["Storm data unavailable."]
