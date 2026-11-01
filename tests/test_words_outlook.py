"""The outlook sentences, from the saved gtwo shapefiles and outlook texts."""

from dataclasses import replace

import pytest

from eyewall.models.outlook import Outlook, OutlookGis
from eyewall.providers.nhc.text import parse_two
from eyewall.providers.nhc.two import parse_gtwo_zip
from eyewall.ui.words.outlook import outlook_sentences
from tests.nhc_fixtures import gis_bytes, nhc_text
from tests.words_support import assert_traces


def gis(name: str) -> OutlookGis:
    return parse_gtwo_zip(gis_bytes(name))


def two(*names: str):
    return tuple(parse_two(nhc_text(f"two/{name}.txt")) for name in names)


def texts(outlook: Outlook, words):
    return [assert_traces(w, outlook=outlook).text for w in words]


def test_one_area_reads_as_a_single_sentence_with_an_before_80():
    outlook = Outlook(gis=gis("gtwo_20250926.zip"))
    assert texts(outlook, outlook_sentences(outlook, ("AL", "EP", "CP"))) == [
        "NHC is watching 1 area: an 80% chance it forms within 2 days and 90% within 7 days."
    ]


def test_several_areas_get_a_lead_and_a_line_each():
    outlook = Outlook(gis=gis("gtwo_20250919.zip"))
    assert texts(outlook, outlook_sentences(outlook, ("AL", "EP", "CP"))) == [
        "NHC is watching 3 areas.",
        "Atlantic area 1: a 0% chance it forms within 2 days and 20% within 7 days.",
        "Pacific area 1: a 60% chance it forms within 2 days and 60% within 7 days.",
        "Pacific area 2: a 20% chance it forms within 2 days and 60% within 7 days.",
    ]


def test_only_areas_in_the_enabled_basins_are_counted():
    outlook = Outlook(gis=gis("gtwo_20250919.zip"))
    assert texts(outlook, outlook_sentences(outlook, ("AL",))) == [
        "NHC is watching 1 area: a 0% chance it forms within 2 days and 20% within 7 days."
    ]
    assert texts(outlook, outlook_sentences(outlook, ("CP",)))[0] == "NHC is watching 2 areas."


def test_with_no_area_the_outlook_summary_is_said_as_issued():
    outlook = Outlook(texts=two("at_20261031"), gis=gis("gtwo_20261031.zip"))
    assert texts(outlook, outlook_sentences(outlook, ("AL",))) == [
        "Tropical cyclone formation is not expected during the next 7 days."
    ]


def test_the_same_summary_is_not_said_twice():
    one = two("at_20261031")[0]
    outlook = Outlook(texts=(one, replace(one, office="again")))
    assert len(outlook_sentences(outlook, ("AL",))) == 1


def test_when_the_shapes_did_not_arrive_the_text_areas_are_used():
    outlook = Outlook(texts=two("ep_20261031"))
    assert texts(outlook, outlook_sentences(outlook, ("EP",))) == [
        "NHC is watching 1 area: a 0% chance it forms within 2 days and 40% within 7 days."
    ]


def test_text_areas_of_a_basin_that_is_off_are_left_out():
    outlook = Outlook(texts=two("at_special_20261021"))
    assert texts(outlook, outlook_sentences(outlook, ("EP",))) == ["No outlook has been issued yet."]
    both = texts(outlook, outlook_sentences(outlook, ("AL",)))
    assert both[0] == "NHC is watching 2 areas."
    assert both[1] == "Atlantic area 1: a 70% chance it forms within 2 days and 70% within 7 days."


@pytest.mark.parametrize(
    ("outlook", "expected"),
    [
        (None, "Waiting for the first outlook."),
        (Outlook(), "No outlook has been issued yet."),
    ],
)
def test_no_outlook_yet(outlook, expected):
    assert [w.text for w in outlook_sentences(outlook, ("AL",))] == [expected]
