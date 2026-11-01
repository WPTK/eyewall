"""CI-safe tests of the real-input harness itself: no exe, no pseudo-console. They run in the default suite."""

from __future__ import annotations

import socket

import pytest

pyte = pytest.importorskip("pyte")

from .app import help_tokens, parse_crumb, parse_footer, parse_help, sense_violations  # noqa: E402
from .netproxy import Proxy  # noqa: E402
from .walk import header_clock  # noqa: E402

FOOTER = " +/- zoom  f fit  enter open  b buoys  t NHC text" + " " * 40 + "? help  ^p menu  q quit"


def test_footer_cells_have_positions() -> None:
    cells = parse_footer(FOOTER, 29)
    assert [(c.key, c.label) for c in cells] == [
        ("+/-", "zoom"),
        ("f", "fit"),
        ("enter", "open"),
        ("b", "buoys"),
        ("t", "NHC text"),
        ("?", "help"),
        ("^p", "menu"),
        ("q", "quit"),
    ]
    b = cells[3]
    assert FOOTER[b.x : b.end] == "b buoys"
    assert FOOTER[b.mid] in "b buoys"


def test_crumb_segments_and_columns() -> None:
    line = "Home › Erin › Buoys and gauges" + " " * 20 + "3 alerts  Tue 19 Aug 03:25Z"
    segs = parse_crumb(line)
    assert [s for s, _ in segs] == ["Home", "Erin", "Buoys and gauges"]
    assert line[segs[2][1] :].startswith("Buoys and gauges")
    assert parse_crumb("Home                   3 alerts") == [("Home", 0)]


HELP = [
    "                     ╭──────────────────────────────╮",
    "                     │  Map                         │",
    "                     │  j  k  Enter    previous or next storm; open its page │",
    "                     │  1  2  3  a     Atlantic, East Pacific                │",
    "                     │  +/-            zoom in                  │",
    "                     │  Anywhere                    │",
    "                     │  Esc  Backspace   go back one screen          │",
    "                     │                 and a continuation          │",
    "                     │  [  ]           previous or next advisory ▌ toast text",
]


def test_help_rows_and_tokens() -> None:
    rows, section = parse_help(HELP)
    assert [(s, k) for s, k, _ in rows] == [
        ("Map", "j  k  Enter"),
        ("Map", "1  2  3  a"),
        ("Map", "+/-"),
        ("Anywhere", "Esc  Backspace"),
        ("Anywhere", "[  ]"),
    ]
    assert section == "Anywhere"
    assert help_tokens("j  k  Enter") == ["j", "k", "Enter"]
    assert help_tokens("1  2  3  a") == ["1", "2", "3", "a"]
    assert help_tokens("+/-") == ["+", "-"]
    assert help_tokens("[  ]") == ["[", "]"]
    assert help_tokens("left/right") == ["Left", "Right"]


def _screen(*rows: str, cols: int = 80, height: int = 24) -> list[str]:
    lines = list(rows) + [""] * (height - len(rows))
    lines[-1] = lines[-1] or "? ^p esc"
    return lines


def test_sense_rules_catch_contradictions() -> None:
    ok = _screen("Home" + " " * 40 + "3 alerts  Tue 19 Aug 03:25Z  ▶ replay 300x")
    ok[-1] = "enter open" + " " * 40 + "? help  ^p menu  q quit"
    assert sense_violations(ok, 80, 24) == []
    both = list(ok)
    both[0] = "Home" + " " * 40 + "▶ replay paused"
    assert any("playing and paused" in v for v in sense_violations(both, 80, 24))
    quit_deep = list(ok)
    quit_deep[0] = "Home › Erin" + " " * 40 + "3 alerts"
    assert any("quit away" in v for v in sense_violations(quit_deep, 80, 24))
    trace = list(ok)
    trace[5] = "Traceback (most recent call last):"
    assert any("Traceback" in v for v in sense_violations(trace, 80, 24))
    assert any("blank" in v for v in sense_violations([""] * 24, 80, 24))
    grammar = list(ok)
    grammar[0] = "Home" + " " * 40 + "✕ 1 feeds failing"
    assert any("grammar" in v for v in sense_violations(grammar, 80, 24))


def test_pyte_roundtrip_of_an_sgr_screen() -> None:
    screen = pyte.Screen(20, 3)
    stream = pyte.Stream(screen)
    stream.feed("\x1b[7m●\x1b[0m ok")
    assert screen.display[0].startswith("● ok")
    assert screen.buffer[0][0].reverse and not screen.buffer[0][2].reverse


def test_header_clock_reads_the_replay_time() -> None:
    class Fake:
        def header_status(self) -> str:
            return "3 alerts  Tue 19 Aug 03:25Z adv 31  ▶ replay 300x"

    assert header_clock(Fake()) == "Tue 19 Aug 03:25Z"  # type: ignore[arg-type]


def test_proxy_refuses_while_blocked_and_counts_requests() -> None:
    p = Proxy(blocked=True)
    try:
        with socket.create_connection(("127.0.0.1", p.port), timeout=5) as s:
            s.sendall(b"CONNECT example.invalid:443 HTTP/1.1\r\nHost: example.invalid:443\r\n\r\n")
            assert s.recv(100).startswith(b"HTTP/1.1 503")
        assert p.requests == ["CONNECT example.invalid:443 HTTP/1.1"]
    finally:
        p.close()
