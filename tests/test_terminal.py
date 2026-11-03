"""Terminal capability detection, exit hygiene, the crash log and --diagnose."""

from __future__ import annotations

import io
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


def test_apply_sets_textual_colour_system_and_no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    from textual import constants

    monkeypatch.setattr(constants, "COLOR_SYSTEM", "auto")
    monkeypatch.delenv("NO_COLOR", raising=False)
    terminal.apply(caps({"TERM": "xterm-256color"}))
    assert constants.COLOR_SYSTEM == "256"
    terminal.apply(caps({"TERM": "dumb"}))
    import os

    assert os.environ["NO_COLOR"] == "1"


def test_restore_sequence_undoes_mouse_alt_screen_and_cursor() -> None:
    for code in ("?1000l", "?1006l", "?2004l", "?25h", "?1049l"):
        assert f"\x1b[{code}" in RESTORE_SEQUENCE


class Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_restore_writes_to_a_terminal_only() -> None:
    tty, pipe = Tty(), io.StringIO()
    terminal.restore(tty)
    terminal.restore(pipe)
    assert tty.getvalue() == RESTORE_SEQUENCE
    assert pipe.getvalue() == ""


def test_a_crash_restores_the_terminal_logs_and_names_the_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(diagnostics, "log_dir", lambda: tmp_path)
    restored: list[bool] = []
    monkeypatch.setattr(terminal, "restore", lambda stream=None: restored.append(True))
    monkeypatch.setattr(terminal, "apply", lambda c: None)

    def boom() -> int:
        raise RuntimeError(f"broke under {Path.home()}")

    assert cli._guarded(boom, caps({})) == 1
    err = capsys.readouterr().err
    logs = list(tmp_path.glob("crash-*.log"))
    assert len(logs) == 1
    assert str(logs[0]) in err or logs[0].name in err
    assert diagnostics.ISSUES_URL in err
    text = logs[0].read_text(encoding="utf-8")
    assert "RuntimeError" in text and str(Path.home()) not in text
    assert restored  # at least once, and again on the way out


def test_ctrl_c_restores_the_terminal_and_exits_130(monkeypatch: pytest.MonkeyPatch) -> None:
    restored: list[bool] = []
    monkeypatch.setattr(terminal, "restore", lambda stream=None: restored.append(True))
    monkeypatch.setattr(terminal, "apply", lambda c: None)

    def interrupt() -> int:
        raise KeyboardInterrupt

    assert cli._guarded(interrupt, caps({})) == 130
    assert restored


def test_old_crash_logs_are_pruned(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(diagnostics, "log_dir", lambda: tmp_path)
    for day in range(1, 16):
        diagnostics.write_crash_log(ValueError("x"), caps({}), now=datetime(2026, 1, day, 12))
    assert len(list(tmp_path.glob("crash-*.log"))) == diagnostics.KEEP_LOGS


def test_diagnose_prints_the_report_without_starting_the_app(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    from eyewall.headless import HeadlessResult

    async def fake_live(config, state_dir, until, *, emit=None):  # type: ignore[no-untyped-def]
        return HeadlessResult(feeds_ok=3, feeds_failed=1, failed_feeds={"alerts"})

    monkeypatch.setattr("eyewall.headless.run_live", fake_live)
    monkeypatch.setattr(cli, "_run_app", lambda *a, **k: pytest.fail("the app must not start"))
    assert cli.main(["--diagnose", "--no-config"]) == 0
    out = capsys.readouterr().out
    assert "eyewall " in out and "python " in out and "capabilities color=" in out
    assert "feeds 3 ok, 1 failed (alerts)" in out
    assert "crash logs" in out
    assert str(Path.home()) not in out
