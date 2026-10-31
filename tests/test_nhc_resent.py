"""NHC appends "...RESENT" to a re-sent product's heading; the heading must still parse (found recording Erin 2025)."""

import pytest

from eyewall.models.storm import AdvNum
from eyewall.providers.nhc.tcm import parse_tcm
from eyewall.providers.nhc.text import parse_pws, parse_tcd, parse_tcp
from tests.nhc_fixtures import nhc_text


@pytest.mark.parametrize(
    ("path", "parse", "heading"),
    [
        ("tcm/erin_030.txt", parse_tcm, "HURRICANE ERIN FORECAST/ADVISORY NUMBER  30"),
        ("tcp/erin_030.txt", parse_tcp, "Hurricane Erin Advisory Number  30"),
        ("tcd/erin_030.txt", parse_tcd, "Hurricane Erin Discussion Number  30"),
        ("pws/erin_030.txt", parse_pws, "HURRICANE ERIN WIND SPEED PROBABILITIES NUMBER  30"),
    ],
)
def test_a_resent_heading_parses_like_the_original(path, parse, heading):
    text = nhc_text(path)
    assert heading in text
    resent = text.replace(heading, heading + "...RESENT")
    assert parse(resent).adv_num == AdvNum(30)
