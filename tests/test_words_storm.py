"""The storm sentences, built from the saved Erin payloads, in every unit preset."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from eyewall.models.advisory import WatchWarningText
from eyewall.models.storm import AdvNum, Classification
from eyewall.palette import WatchWarning
from eyewall.state.store import StormState
from eyewall.ui.words import distance_text, round5, wind_text
from eyewall.ui.words import storm as sw
from eyewall.ui.words.about import parse_about, place_name
from eyewall.ui.words.glossary import MEANINGS, quoted_meanings
from eyewall.units import PRESETS
from tests.nhc_fixtures import nhc_text
from tests.state_support import area, make_public, make_storm
from tests.words_support import assert_traces, erin_state

EDT = timezone(timedelta(hours=-4), "EDT")
NOW = datetime(2025, 8, 19, 2, 7, tzinfo=UTC)


def traced(words, state):
    return assert_traces(words, state=state, states=[state])


# ------------------------------------------------------------------------------------------------- the about lines


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("ABOUT 695 MI...1120 KM SW OF BERMUDA", (695, 1120, "SW", "Bermuda")),
        (
            "ABOUT 815 MI...1310 KM SSE OF CAPE HATTERAS NORTH CAROLINA",
            (815, 1310, "SSE", "Cape Hatteras North Carolina"),
        ),
        (
            "ABOUT 130 MI...210 KM S OF THE MOUTH OF THE MISSISSIPPI RIVER",
            (130, 210, "S", "The Mouth of the Mississippi River"),
        ),
        ("ABOUT 40 MI NORTHEAST OF SAN JUAN PUERTO RICO", (40, None, "NE", "San Juan Puerto Rico")),
        ("about 60 mi...95 km wnw of winston-salem", (60, 95, "WNW", "Winston-Salem")),
    ],
)
def test_about_lines_are_read_into_miles_km_direction_and_place(line, expected):
    about = parse_about(line)
    assert about is not None
    assert (about.miles, about.km, about.direction, about.place) == expected


@pytest.mark.parametrize(
    "line", ["", "LOCATION...24.0N 71.3W", "ABOUT 12 MI...20 KM XYZ OF NOWHERE", "ABOUT MANY MI SW OF X"]
)
def test_a_line_that_is_not_an_about_line_is_ignored(line):
    assert parse_about(line) is None


def test_place_names_get_their_case_back():
    assert place_name("ST. CROIX") == "St. Croix"


# ------------------------------------------------------------------------------------------------------- unit rules


@pytest.mark.parametrize(
    ("preset", "kt", "mph", "expected"),
    [
        ("nautical", 120, 140, "120 kt"),
        ("us", 120, 140, "140 mph"),  # rule 1: NHC's own 140, not the 138 that 120 kt converts to
        ("metric", 120, 140, "220 km/h"),  # rounded to 5 as NHC prints it, not the 222 that 120 kt converts to
        ("us", 120, None, "140 mph"),  # worked out from knots, rounded to 5
        ("us", None, 140, "140 mph"),
        ("nautical", None, 140, "120 kt"),
    ],
)
def test_storm_winds_follow_rule_one(preset, kt, mph, expected):
    assert wind_text(PRESETS[preset], kt=kt, mph=mph) == expected


def test_a_wind_with_no_source_is_none():
    assert wind_text(PRESETS["us"]) is None


@pytest.mark.parametrize(
    ("preset", "expected"),
    [("nautical", "605 nm"), ("us", "695 mi"), ("metric", "1120 km")],
)
def test_distances_follow_rule_two(preset, expected):
    assert distance_text(PRESETS[preset], mi=695, km=1120) == expected  # nm is 695 mi rounded to 5


def test_nautical_miles_are_rounded_to_5_and_a_distance_needs_a_source():
    assert round5(603.9) == 605
    assert distance_text(PRESETS["us"], nm=200) == "230 mi"
    with pytest.raises(ValueError):
        distance_text(PRESETS["us"])


# ----------------------------------------------------------------------------------------------------------- the lead


@pytest.mark.parametrize(
    ("preset", "text"),
    [
        (
            "nautical",
            "Hurricane Erin, Category 4, is about 605 nm SW of Bermuda and 710 nm SSE of Cape Hatteras North Carolina "
            "and moving NW at 9 kt.",
        ),
        (
            "us",
            "Hurricane Erin, Category 4, is about 695 mi SW of Bermuda and 815 mi SSE of Cape Hatteras North Carolina "
            "and moving NW at 10 mph.",
        ),
        (
            "metric",
            "Hurricane Erin, Category 4, is about 1120 km SW of Bermuda and 1310 km SSE of Cape Hatteras North Carolina "
            "and moving NW at 17 km/h.",
        ),
    ],
)
def test_the_storm_lead_in_each_preset(preset, text):
    state = erin_state()
    words = traced(sw.storm_lead(state, PRESETS[preset]), state)
    assert words.text == text
    assert "state.advisories.public.summary.about[0]" in words.sources
    assert "state.storm.intensity_kt" in words.sources


def test_without_the_public_advisory_the_lead_uses_the_feeds_position_and_movement():
    state = erin_state(public=False, forecast=False)
    words = traced(sw.storm_lead(state, PRESETS["us"]), state)
    assert words.text == "Hurricane Erin, Category 4, is at 24.0N 71.3W and moving NW at 10 mph."


def test_an_advisory_that_is_not_the_feeds_is_not_trusted():
    state = erin_state()
    older = replace(state.storm, public_advisory=replace(state.storm.public_advisory, adv_num=AdvNum(31)))
    stale = replace(state, storm=older)
    assert sw.current_public(stale) is None
    assert "Bermuda" not in sw.storm_lead(stale, PRESETS["us"]).text
    assert sw.warning_sentences(stale) == []
    assert sw.next_advisory(stale) is None


def test_a_forecast_for_another_advisory_gives_no_size_and_no_forecast():
    state = erin_state()
    other = replace(state.storm, forecast_advisory=replace(state.storm.forecast_advisory, adv_num=AdvNum(31)))
    stale = replace(state, storm=other)
    assert sw.size_sentence(stale, PRESETS["us"]) is None
    assert sw.forecast_rows(stale, PRESETS["us"], EDT) == []
    assert sw.strongest(stale, EDT) is None


@pytest.mark.parametrize(
    ("classification", "intensity", "kind", "label"),
    [
        (Classification.TS, 50, "Tropical Storm", "tropical storm"),
        (Classification.TD, 30, "Tropical Depression", "tropical depression"),
        (Classification.HU, 140, "Hurricane", "Cat 5"),
        (Classification.HU, 70, "Hurricane", "Cat 1"),
        (Classification.PTC, 40, "Potential Tropical Cyclone", "potential tropical cyclone"),
        (Classification.STS, 40, "Subtropical Storm", "subtropical storm"),
        (Classification.PC, 25, "Post-Tropical Cyclone", "post-tropical cyclone"),
    ],
)
def test_kind_and_short_label(classification, intensity, kind, label):
    storm = replace(make_storm(classification=classification), intensity_kt=intensity)
    assert sw.storm_kind(storm) == kind
    assert sw.short_label(storm) == label


def test_a_storm_that_is_not_a_hurricane_has_no_category_in_its_lead():
    storm = make_storm(name="Ana")
    state = StormState(storm)
    words = traced(sw.storm_lead(state, PRESETS["us"]), state)
    assert words.text == "Tropical Storm Ana is at 25.0N 75.0W and moving WNW at 10 mph."


def test_a_nearly_stationary_storm_is_said_to_be_so():
    storm = replace(make_storm(), movement_speed_mph=0.0)
    assert sw.storm_lead(StormState(storm), PRESETS["us"]).text.endswith("and nearly stationary.")


def test_a_storm_with_nothing_known_still_gets_a_sentence():
    storm = replace(make_storm(), lat=None, lon=None, movement_dir_deg=None, movement_speed_mph=None)
    assert sw.storm_lead(StormState(storm), PRESETS["us"]).text == "Tropical Storm Ana."


@pytest.mark.parametrize(
    ("preset", "text"),
    [
        ("nautical", "Maximum sustained winds are 120 kt."),
        ("us", "Maximum sustained winds are 140 mph (120 kt)."),
        ("metric", "Maximum sustained winds are 220 km/h (120 kt)."),
    ],
)
def test_the_wind_sentence_in_each_preset(preset, text):
    state = erin_state()
    assert traced(sw.storm_wind(state, PRESETS[preset], with_knots=True), state).text == text
    assert sw.storm_wind(state, PRESETS[preset]).text == text.replace(" (120 kt)", "")


def test_the_wind_in_mph_is_nhcs_own_figure_from_the_advisory():
    state = erin_state()
    words = sw.storm_wind(state, PRESETS["us"])
    assert words.sources == ("state.advisories.public.summary.max_wind_mph",)
    assert state.advisories.public.summary.max_wind_mph == 140


def test_updated_age_and_next_advisory():
    state = erin_state()
    assert traced(sw.updated(state.storm, NOW), state).text == "Updated 2h07m ago."
    assert sw.updated(replace(state.storm, last_update=None), NOW).text == "No advisory time is known yet."
    assert traced(sw.next_advisory(state), state).text == (
        "Next intermediate advisory at 800 PM EDT. Next complete advisory at 1100 PM EDT."
    )


# ------------------------------------------------------------------------------------------ several and no storms


def test_several_storms_name_each_and_say_who_has_warnings():
    erin = erin_state()
    fern = StormState(
        replace(make_storm(name="Fernand", storm_id="al062025"), intensity_kt=50),
    )
    words = assert_traces(sw.several_storms([erin, fern]), states=[erin, fern])
    assert words.text == "2 storms: Erin (Cat 4) and Fernand (tropical storm). Erin has warnings in effect."


def test_several_storms_with_only_watches_and_with_none():
    watched = StormState(
        make_storm(name="Ana"),
        advisories=replace(erin_state().advisories, public=make_public("1", area("TROPICAL STORM WATCH", "Cuba"))),
    )
    plain = StormState(make_storm(name="Bill", storm_id="al022026"))
    assert sw.several_storms([watched, plain]).text == (
        "2 storms: Ana (tropical storm) and Bill (tropical storm). Ana has watches in effect."
    )
    assert sw.several_storms([plain, plain]).text == ("2 storms: Bill (tropical storm) and Bill (tropical storm).")


@pytest.mark.parametrize(
    ("basins", "text"),
    [
        (("AL",), "No tropical storms in the Atlantic right now."),
        (("AL", "EP"), "No tropical storms in the Atlantic and East Pacific right now."),
        (("AL", "EP", "CP"), "No tropical storms in the Atlantic, East Pacific and Central Pacific right now."),
    ],
)
def test_nothing_active_names_the_enabled_basins(basins, text):
    assert sw.nothing_active(basins).text == text


# ------------------------------------------------------------------------------------------- watches and warnings


def test_warnings_say_expected_and_watches_say_possible_most_serious_first():
    state = erin_state()
    sentences = [traced(w, state).text for w in sw.warning_sentences(state)]
    assert sentences == [
        "Tropical storm conditions are expected in Turks and Caicos Islands and Southeast Bahamas.",
        "Tropical storm conditions are possible in Central Bahamas and Beaufort Inlet to Duck, North Carolina "
        "including Pamlico Sound.",
        "Life-threatening storm surge is possible in Cape Lookout to Duck, North Carolina.",
    ]


def test_hurricane_warnings_come_before_tropical_storm_warnings_and_long_lists_are_cut():
    public = make_public(
        "30",
        area("TROPICAL STORM WARNING", "A", "B"),
        area("HURRICANE WARNING", "Florida Keys", "Miami", "Naples", "Tampa"),
    )
    state = StormState(make_storm("30"), advisories=replace(erin_state().advisories, public=public))
    first, second = (w.text for w in sw.warning_sentences(state))
    assert first == "Hurricane conditions are expected in Florida Keys and Miami, +2 more."
    assert second == "Tropical storm conditions are expected in A and B."


def test_a_label_the_app_does_not_know_is_still_said():
    from eyewall.models.watches import WatchWarningArea

    odd = WatchWarningArea("Special Marine Statement", None, ("Gulf Stream",))
    public = replace(make_public("30"), watches_warnings=WatchWarningText(in_effect=(odd,)))
    state = StormState(make_storm("30"), advisories=replace(erin_state().advisories, public=public))
    assert [w.text for w in sw.warning_sentences(state)] == ["Special Marine Statement is in effect in Gulf Stream."]
    assert sw.meaning_sentences(state) == []


def test_the_meanings_are_quoted_exactly_from_the_advisory():
    state = erin_state()
    sentences = [traced(w, state) for w in sw.meaning_sentences(state)]
    assert [w.text for w in sentences] == [
        "A Tropical Storm Warning means that tropical storm conditions are expected somewhere within the warning area.",
        "A Tropical Storm Watch means that tropical storm conditions are possible within the watch area, "
        "generally within 48 hours.",
        "A Storm Surge Watch means there is a possibility of life-threatening inundation, from rising water moving "
        "inland from the coastline, in the indicated locations during the next 48 hours.",
    ]
    assert all(w.sources == ("state.advisories.public.watches_warnings.text",) for w in sentences)


def test_each_quoted_meaning_is_a_sentence_of_the_saved_advisory():
    text = nhc_text("tcp/erin_030.txt")
    for sentence in quoted_meanings(text).values():
        assert sentence.split(" ")[0] in ("A", "An")
        assert " ".join(sentence.replace("-", "- ").split()).split(" ")[-1]  # not empty
    assert (
        "life-threatening inundation" in quoted_meanings(text)[("storm surge", "watch")]
    )  # the wrapped hyphen is joined


def test_when_the_advisory_has_no_meaning_sentences_the_glossary_wording_is_used():
    area_list = (
        area("HURRICANE WARNING", "Miami"),
        area("HURRICANE WATCH", "Naples"),
        area("TROPICAL STORM WARNING", "Tampa"),
        area("TROPICAL STORM WATCH", "Key West"),
    )
    public = replace(make_public("30", *area_list), watches_warnings=WatchWarningText(in_effect=area_list, text=""))
    state = StormState(make_storm("30"), advisories=replace(erin_state().advisories, public=public))
    words = [traced(w, state) for w in sw.meaning_sentences(state)]
    assert [w.text for w in words] == [
        MEANINGS[("hurricane", "warning")],
        MEANINGS[("hurricane", "watch")],
        MEANINGS[("tropical storm", "warning")],
        MEANINGS[("tropical storm", "watch")],
    ]
    assert "expected somewhere within the warning area" in words[0].text
    assert "possible within the watch area, generally within 48 hours" in words[1].text


def test_surge_kinds_are_told_apart_from_the_enum_not_just_the_label():
    from eyewall.models.watches import WatchWarningArea

    warn = WatchWarningArea("Storm Surge Warning", WatchWarning.SURGE_WARNING, ("Galveston",))
    public = replace(make_public("30"), watches_warnings=WatchWarningText(in_effect=(warn,)))
    state = StormState(make_storm("30"), advisories=replace(erin_state().advisories, public=public))
    assert sw.warning_sentences(state)[0].text == "Life-threatening storm surge is expected in Galveston."
    assert sw.meaning_sentences(state)[0].text == MEANINGS[("storm surge", "warning")]


# ---------------------------------------------------------------------------------------------- size and forecast


@pytest.mark.parametrize(
    ("preset", "text"),
    [
        (
            "nautical",
            "Tropical-storm-force winds (34+ kt) reach up to 200 nm from the centre; hurricane-force (64+ kt) to 70 nm.",
        ),
        (
            "us",
            "Tropical-storm-force winds (39+ mph) reach up to 230 mi from the centre; hurricane-force (74+ mph) to 80 mi.",
        ),
        (
            "metric",
            "Tropical-storm-force winds (63+ km/h) reach up to 370 km from the centre; hurricane-force (119+ km/h) to "
            "130 km.",
        ),
    ],
)
def test_the_size_sentence_in_each_preset(preset, text):
    state = erin_state()
    assert traced(sw.size_sentence(state, PRESETS[preset]), state).text == text


def test_a_storm_without_hurricane_force_winds_says_only_tropical_storm_force():
    state = erin_state()
    tcm = state.advisories.forecast
    no64 = replace(tcm, radii=replace(tcm.radii, kt64=None))
    state = replace(state, advisories=replace(state.advisories, forecast=no64))
    assert sw.size_sentence(state, PRESETS["us"]).text == (
        "Tropical-storm-force winds (39+ mph) reach up to 230 mi from the centre."
    )
    gone = replace(tcm, radii=replace(tcm.radii, kt34=None))
    assert sw.size_sentence(replace(state, advisories=replace(state.advisories, forecast=gone)), PRESETS["us"]) is None


def test_the_forecast_rows_in_local_time_with_the_days_four_and_five_note():
    state = erin_state()
    rows = [traced(w, state) for w in sw.forecast_rows(state, PRESETS["us"], EDT)]
    assert rows[0].text == "Tue 02:00 AM EDT  Category 4  140 mph  24.9N 71.9W"
    assert rows[5].text == "Thu 02:00 PM EDT  Category 2  110 mph  34.8N 71.2W"
    assert rows[-1].text == "96 and 120 hour positions are the extended outlook, not a forecast."
    assert len(rows) == len(state.advisories.forecast.fixes) + 1


def test_forecast_rows_in_knots_and_with_a_dissipating_fix():
    state = erin_state()
    assert (
        sw.forecast_rows(state, PRESETS["nautical"], EDT)[0].text == "Tue 02:00 AM EDT  Category 4  120 kt  24.9N 71.9W"
    )
    tcm = state.advisories.forecast
    gone = replace(tcm.fixes[-1], dissipated=True, lat=None, lon=None, max_wind_kt=None)
    remnant = replace(tcm.fixes[-2], status="POST-TROP/REMNT LOW")
    state = replace(
        state, advisories=replace(state.advisories, forecast=replace(tcm, fixes=(*tcm.fixes[:-2], remnant, gone)))
    )
    rows = [w.text for w in sw.forecast_rows(state, PRESETS["us"], EDT)]
    assert "remnant low" in rows[-3]
    assert rows[-2].endswith("dissipated")


def test_strongest_says_now_and_then_what_follows():
    state = erin_state()
    assert traced(sw.strongest(state, EDT), state).text == "Strongest: Category 4 now, then weakening."


def test_strongest_later_and_holding():
    state = erin_state()
    tcm = state.advisories.forecast
    storm = replace(state.storm, intensity_kt=70)
    base = replace(state, storm=storm)
    fixes = tuple(replace(f, max_wind_kt=100 if f.tau == 48 else 98) for f in tcm.fixes)
    later = replace(base, advisories=replace(base.advisories, forecast=replace(tcm, fixes=fixes)))
    assert sw.strongest(later, EDT).text == "Strongest: Category 3 on Wednesday, then holding."
    rising = tuple(replace(f, max_wind_kt=70 + f.tau // 2) for f in tcm.forecast_fixes)
    still = replace(base, advisories=replace(base.advisories, forecast=replace(tcm, fixes=rising)))
    assert sw.strongest(still, EDT).text.endswith("strengthening through the forecast.")
    assert sw.strongest(replace(state, storm=replace(storm, intensity_kt=None)), EDT) is None
