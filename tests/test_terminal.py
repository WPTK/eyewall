"""Terminal capability detection, exit hygiene, the crash log and --diagnose."""

from __future__ import annotations

import asyncio
import getpass
import io
import os
import signal
import sys
from datetime import datetime
from pathlib import Path

import pytest

from eyewall import cli, diagnostics, terminal
from eyewall.terminal import RESTORE_SEQUENCE, detect

UTF8 = "utf-8"


def caps(env: dict[str, str], encoding: str = UTF8, windows: bool = False) -> terminal.Capabilities:
    return detect(env, encoding=encoding, size=(80, 24), windows=windows)


@pytest.mark.parametrize(
    ("env", "color"),
    [
        ({"COLORTERM": "truecolor", "TERM": "xterm-256color"}, "truecolor"),
        ({"COLORTERM": "24bit"}, "truecolor"),
        ({"TERM": "xterm-256color"}, "256"),
        ({"TERM": "tmux-256color"}, "256"),
        ({"TERM": "screen"}, "16"),
        ({"TERM": "xterm"}, "16"),
        ({"TERM": "dumb"}, "none"),
        ({"NO_COLOR": "1", "COLORTERM": "truecolor"}, "none"),
    ],
)
def test_colour_depth_follows_colorterm_then_term(env: dict[str, str], color: str) -> None:
    assert caps(env).color == color


def test_windows_terminal_is_truecolor_and_a_bare_console_is_256() -> None:
    assert caps({"WT_SESSION": "x"}, windows=True).color == "truecolor"
    assert caps({}, windows=True).color == "256"


def test_rich_colour_system_names() -> None:
    assert caps({"COLORTERM": "truecolor"}).rich_color_system == "truecolor"
    assert caps({"TERM": "xterm"}).rich_color_system == "standard"
    assert caps({"TERM": "dumb"}).rich_color_system is None


@pytest.mark.parametrize(
    ("env", "encoding", "windows", "unicode"),
    [
        ({"TERM": "xterm-256color", "LANG": "en_US.UTF-8"}, UTF8, False, True),
        ({"TERM": "xterm-256color", "LANG": "C"}, UTF8, False, False),
        ({"TERM": "xterm-256color", "LANG": "en_US.UTF-8"}, "ascii", False, False),
        ({"TERM": "linux", "LANG": "en_US.UTF-8"}, UTF8, False, False),
        ({"TERM": "dumb"}, UTF8, False, False),
        ({"WT_SESSION": "x"}, UTF8, True, True),
        ({}, "cp1252", True, False),
        ({}, UTF8, True, False),  # the legacy console host, even with UTF-8 output
        ({"TERM": "screen", "LC_ALL": "en_US.UTF-8"}, UTF8, False, True),  # tmux over SSH
    ],
)
def test_unicode_needs_a_utf8_locale_and_a_terminal_that_draws_it(
    env: dict[str, str], encoding: str, windows: bool, unicode: bool
) -> None:
    assert caps(env, encoding, windows).unicode is unicode


def test_windows_terminal_hints_beat_a_term_guess() -> None:
    assert caps({"WT_SESSION": "x", "TERM": "xterm"}, windows=True).color == "truecolor"


def test_apply_sets_textual_colour_system_only_when_it_knows(monkeypatch: pytest.MonkeyPatch) -> None:
    from textual import constants

    monkeypatch.setattr(constants, "COLOR_SYSTEM", "auto")
    monkeypatch.delenv("NO_COLOR", raising=False)
    terminal.apply(caps({"TERM": "xterm-256color"}))
    assert constants.COLOR_SYSTEM == "256"
    monkeypatch.setattr(constants, "COLOR_SYSTEM", "auto")
    terminal.apply(caps({"TERM": "xterm"}))
    assert constants.COLOR_SYSTEM == "auto"  # 16 colours: left to Textual
    terminal.apply(caps({"TERM": "dumb"}))
    assert constants.COLOR_SYSTEM is None
    assert os.environ["NO_COLOR"] == "1"


def test_restore_sequence_undoes_mouse_alt_screen_and_cursor() -> None:
    for code in ("?1000l", "?1006l", "?2004l", "?25h", "?1049l"):
        assert f"\x1b[{code}" in RESTORE_SEQUENCE


class Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_restore_writes_the_sequence_to_the_stream_it_is_given() -> None:
    tty = Tty()
    terminal.restore(tty)
    assert tty.getvalue() == RESTORE_SEQUENCE


@pytest.mark.parametrize("platform_name", ["linux", "win32"])
def test_the_stream_is_whichever_of_stdout_and_stderr_is_a_terminal(
    monkeypatch: pytest.MonkeyPatch, platform_name: str
) -> None:
    out, err = io.StringIO(), Tty()
    monkeypatch.setattr(sys, "platform", platform_name)
    monkeypatch.setattr(sys, "__stdout__", out)
    monkeypatch.setattr(sys, "__stderr__", err)
    assert terminal.terminal_stream() is err  # stdout redirected, stderr a terminal
    terminal.restore()
    assert err.getvalue() == RESTORE_SEQUENCE and out.getvalue() == ""
    out2, err2 = Tty(), Tty()
    monkeypatch.setattr(sys, "__stdout__", out2)
    monkeypatch.setattr(sys, "__stderr__", err2)
    assert terminal.terminal_stream() is (out2 if platform_name == "win32" else err2)
    monkeypatch.setattr(sys, "__stdout__", io.StringIO())
    monkeypatch.setattr(sys, "__stderr__", io.StringIO())
    assert terminal.terminal_stream() is None


@pytest.fixture
def guard(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(diagnostics, "log_dir", lambda: tmp_path)
    monkeypatch.setattr(terminal, "restore", lambda stream=None: calls.append("restore"))
    monkeypatch.setattr(terminal, "apply", lambda c: None)
    return calls


def test_a_crash_is_logged_names_the_file_and_restores_once(
    guard: list[str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom() -> int:
        raise RuntimeError(f"broke under {Path.home()}")

    assert cli._guarded(boom, caps({})) == 1
    err = capsys.readouterr().err
    logs = list(tmp_path.glob("crash-*.log"))
    assert len(logs) == 1 and logs[0].name in err and diagnostics.ISSUES_URL in err
    text = logs[0].read_text(encoding="utf-8")
    assert "RuntimeError" in text and str(Path.home()) not in text
    assert guard == ["restore"]


def test_a_clean_exit_leaves_the_terminal_to_textual(guard: list[str]) -> None:
    assert cli._guarded(lambda: 0, caps({})) == 0
    assert guard == []


def test_ctrl_c_restores_once_and_exits_130(guard: list[str]) -> None:
    def interrupt() -> int:
        raise KeyboardInterrupt

    assert cli._guarded(interrupt, caps({})) == 130
    assert guard == ["restore"]


def test_system_exit_restores_and_propagates(guard: list[str], tmp_path: Path) -> None:
    def terminated() -> int:
        raise SystemExit(143)

    with pytest.raises(SystemExit) as raised:
        cli._guarded(terminated, caps({}))
    assert raised.value.code == 143 and guard == ["restore"]
    assert not list(tmp_path.glob("crash-*.log"))


def test_a_cancelled_task_is_logged_as_a_crash(guard: list[str], tmp_path: Path) -> None:
    def cancelled() -> int:
        raise asyncio.CancelledError

    assert cli._guarded(cancelled, caps({})) == 1
    assert len(list(tmp_path.glob("crash-*.log"))) == 1 and guard == ["restore"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_sigterm_during_the_app_becomes_system_exit(guard: list[str]) -> None:
    def killed() -> int:
        os.kill(os.getpid(), signal.SIGTERM)
        return 0

    before = signal.getsignal(signal.SIGTERM)
    with pytest.raises(SystemExit) as raised:
        cli._guarded(killed, caps({}))
    assert raised.value.code == 128 + signal.SIGTERM and guard == ["restore"]
    assert signal.getsignal(signal.SIGTERM) == before


def test_old_crash_logs_are_pruned(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(diagnostics, "log_dir", lambda: tmp_path)
    for day in range(1, 16):
        diagnostics.write_crash_log(ValueError("x"), caps({}), now=datetime(2026, 1, day, 12))
    assert len(list(tmp_path.glob("crash-*.log"))) == diagnostics.KEEP_LOGS


def test_a_prune_failure_does_not_hide_a_written_log(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(diagnostics, "log_dir", lambda: tmp_path)
    monkeypatch.setattr(diagnostics, "KEEP_LOGS", 1)

    def locked(self: Path, missing_ok: bool = False) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(Path, "unlink", locked)
    diagnostics.write_crash_log(ValueError("a"), caps({}), now=datetime(2026, 1, 1))
    path = diagnostics.write_crash_log(ValueError("b"), caps({}), now=datetime(2026, 1, 2))
    assert path is not None and path.exists()


def test_scrub_ignores_case_of_the_home_path_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("C:/Users/Alice")))
    monkeypatch.setattr(os.path, "expanduser", lambda p: "C:\\Users\\Alice")
    monkeypatch.setattr(getpass, "getuser", lambda: "Alice")
    out = diagnostics.scrub("in c:\\users\\ALICE\\x and C:/users/alice/y by alice")
    assert "alice" not in out.lower() and "~" in out and "<user>" in out


def diagnose(monkeypatch: pytest.MonkeyPatch, fake_live, *argv: str) -> int:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("eyewall.headless.run_live", fake_live)
    monkeypatch.setattr(cli, "_run_app", lambda *a, **k: pytest.fail("the app must not start"))
    return cli.main(["--diagnose", *argv])


def test_diagnose_prints_the_report_without_starting_the_app(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    from eyewall.headless import HeadlessResult

    seen: list[object] = []

    async def fake_live(config, state_dir, until, *, emit=None):  # type: ignore[no-untyped-def]
        seen.append(state_dir)
        return HeadlessResult(feeds_ok=3, feeds_failed=1, failed_feeds={"alerts"})

    assert diagnose(monkeypatch, fake_live, "--no-config", "--state-dir", str(tmp_path)) == 0
    out = capsys.readouterr().out
    assert "eyewall " in out and "python " in out and "capabilities color=" in out
    assert "feeds 3 ok, 1 failed (alerts)" in out and "crash logs" in out
    assert seen == [tmp_path] and "data " in out
    assert str(Path.home()) not in out


def test_diagnose_reports_a_config_that_could_not_be_read(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    from eyewall.headless import HeadlessResult

    async def fake_live(config, state_dir, until, *, emit=None):  # type: ignore[no-untyped-def]
        return HeadlessResult()

    bad = tmp_path / "c.toml"
    bad.write_text("[map\nbroken", encoding="utf-8")
    assert diagnose(monkeypatch, fake_live, "--config", str(bad)) == 0
    assert "config file could not be read" in capsys.readouterr().out


def test_diagnose_survives_a_feed_error_and_a_timeout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def broken(config, state_dir, until, *, emit=None):  # type: ignore[no-untyped-def]
        raise OSError("no route")

    assert diagnose(monkeypatch, broken, "--no-config") == 0
    assert "feeds could not be polled: OSError: no route" in capsys.readouterr().out

    async def hangs(config, state_dir, until, *, emit=None):  # type: ignore[no-untyped-def]
        await asyncio.sleep(60)

    monkeypatch.setattr(diagnostics, "FEED_TIMEOUT", 0.05)
    assert diagnose(monkeypatch, hangs, "--no-config") == 0
    assert "did not answer within" in capsys.readouterr().out


def test_ctrl_c_during_diagnose_exits_130(monkeypatch: pytest.MonkeyPatch) -> None:
    async def interrupted(config, state_dir, until, *, emit=None):  # type: ignore[no-untyped-def]
        raise KeyboardInterrupt

    assert diagnose(monkeypatch, interrupted, "--no-config") == 130


def test_an_exception_textual_handles_itself_still_gets_a_crash_log_and_a_failing_status(
    guard: list[str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from textual.app import App

    from eyewall.app import run_checked

    class Broken(App[None]):
        def on_mount(self) -> None:
            raise ValueError("handler broke")

    # Textual prints its own traceback and returns from run(); only run_checked turns that into a crash.
    assert cli._guarded(lambda: run_checked(Broken()) or 0, caps({})) == 1
    err = capsys.readouterr().err
    logs = list(tmp_path.glob("crash-*.log"))
    assert len(logs) == 1 and logs[0].name in err
    assert "ValueError" in logs[0].read_text(encoding="utf-8")
    assert guard == ["restore"]
