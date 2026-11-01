"""Builders for the plain-language tests: real saved payloads in, and a check that every source path names a real field."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from eyewall.models.advisory import AdvisorySet
from eyewall.models.storm import AdvNum, Storm
from eyewall.providers.nhc.current import parse_current_storms
from eyewall.providers.nhc.tcm import parse_tcm
from eyewall.providers.nhc.text import parse_tcp
from eyewall.state.store import StormState
from eyewall.ui.words import Words
from eyewall.ui.words.glossary import MEANINGS
from tests.nhc_fixtures import nhc_bytes, nhc_text

_STEP = re.compile(r"(\w+)|\[(\d+)\]|\[\]")


def erin_storm() -> Storm:
    """Erin from the saved CurrentStorms payload, with the advisory refs set to 30 as the saved text products are."""
    storm = parse_current_storms(nhc_bytes("current/populated.json")).by_id("al052025")
    assert storm is not None
    assert storm.public_advisory is not None
    return replace(storm, public_advisory=replace(storm.public_advisory, adv_num=AdvNum(30)))


def erin_state(*, public: bool = True, forecast: bool = True) -> StormState:
    advisories = AdvisorySet(
        forecast=parse_tcm(nhc_bytes("tcm/erin_030.txt")) if forecast else None,
        public=parse_tcp(nhc_text("tcp/erin_030.txt")) if public else None,
    )
    return StormState(erin_storm(), advisories)


def resolve(root: Any, path: str) -> Any:
    """Follow `a.b[0].c` from `root`; `[]` means every element must have the rest of the path."""
    value = root
    steps = list(_STEP.finditer(path))
    for index, step in enumerate(steps):
        if step[1]:
            value = getattr(value, step[1])
        elif step[2]:
            value = value[int(step[2])]
        else:
            rest = path[steps[index + 1].start() :] if index + 1 < len(steps) else ""
            for item in value:
                resolve(item, rest.lstrip("."))
            return value
    return value


def assert_traces(words: Words | None, **roots: Any) -> Words:
    """Every source of `words` must exist on one of the named roots (the first name in the path picks the root)."""
    assert words is not None
    assert words.text.strip()
    for source in words.sources:
        head = re.match(r"\w+", source)
        assert head is not None, source
        name = head.group(0)
        if name == "glossary":
            key = re.search(r"\['([^']+)', '([^']+)'\]|\[\"([^\"]+)\", \"([^\"]+)\"\]", source)
            assert key is not None and (key[1], key[2]) in MEANINGS, source
        elif name in roots:
            rest = source[len(name) :]
            if rest:
                resolve(roots[name], rest.lstrip("."))
        else:
            raise AssertionError(f"source {source!r} names no root among {sorted(roots)}")
    return words
