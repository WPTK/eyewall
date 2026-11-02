"""Saved real payloads, replayed through the parsers (see `tests/real_corpus.py`).

The recorded fixtures elsewhere in `tests/fixtures` were chosen to exercise a case. This corpus is whatever NOAA served
on a given day, unselected, so a format drift the hand-picked cases never hit shows up here. New days come from
`python scripts/capture_real.py`, which is never run by the test suite.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests import real_corpus as corpus

ALL = list(corpus.captures())


def test_the_corpus_is_not_empty() -> None:
    assert ALL, "tests/fixtures/real has no capture: run scripts/capture_real.py"


@pytest.mark.parametrize("capture", ALL, ids=[c.id for c in ALL])
def test_a_real_payload_parses(capture: corpus.Capture) -> None:
    assert capture.entry["status"] == 200
    assert corpus.replay(capture) is not None


@pytest.mark.parametrize("capture", ALL, ids=[c.id for c in ALL])
def test_a_capture_is_byte_for_byte_what_was_recorded(capture: corpus.Capture) -> None:
    body = capture.body()
    assert corpus.sha256(body) == capture.entry["sha256"]
    assert len(body) == capture.entry["bytes"]


def test_every_capture_kind_has_a_parser_and_every_file_is_listed() -> None:
    for day in corpus.days():
        listed = {c["file"] for c in corpus.manifest(day)}
        on_disk = {p.relative_to(day).as_posix() for p in day.rglob("*") if p.is_file() and p.name != "capture.json"}
        assert listed == on_disk, f"{day.name}: files and capture.json disagree"
        assert {c["kind"] for c in corpus.manifest(day)} <= set(corpus.KINDS)


def test_the_loader_reads_a_day_it_is_given(tmp_path: Path) -> None:
    day = tmp_path / "2026-01-02"
    (day / "outlook_at").mkdir(parents=True)
    (day / "outlook_at" / "a.txt").write_bytes(b"x")
    (day / "capture.json").write_text(
        json.dumps({"captures": [{"kind": "outlook_at", "file": "outlook_at/a.txt", "status": 200}]}), encoding="utf-8"
    )
    found = list(corpus.captures(tmp_path))
    assert [c.id for c in found] == ["2026-01-02/outlook_at"]
    assert found[0].body() == b"x"
