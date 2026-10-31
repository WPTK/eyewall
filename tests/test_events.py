from dataclasses import replace
from datetime import timedelta

from eyewall.models.advisory import AdvisorySet, Discussion
from eyewall.models.events import EventKind
from eyewall.models.outlook import Outlook, OutlookText
from eyewall.models.storm import AdvNum, Classification
from eyewall.models.track import BestTrack, BestTrackFix
from eyewall.models.wind import WindRadii
from eyewall.state import events as ev
from tests.state_support import T0, advisories, area, make_storm, obs, series


def kinds(events):
    return [e.kind for e in events]


# ---- storms -------------------------------------------------------------------------------------------------------


def test_the_first_load_reports_a_new_storm_and_its_advisory():
    storm = make_storm("3")
    events = ev.storm_events(None, {storm.id: storm}, T0)
    assert kinds(events) == [EventKind.NEW_STORM, EventKind.NEW_ADVISORY]
    assert events[1].key == "al012026|3|new_advisory|-"


def test_a_potential_tropical_cyclone_is_reported_as_one():
    storm = make_storm("1", classification=Classification.PTC)
    assert kinds(ev.storm_events(None, {storm.id: storm}, T0))[0] is EventKind.NEW_PTC


def test_an_unchanged_storm_list_produces_nothing():
    storm = make_storm("3")
    assert ev.storm_events({storm.id: storm}, {storm.id: storm}, T0) == []


def test_an_intermediate_advisory_is_a_new_advisory():
    before = make_storm("3")
    after = make_storm("3A", intermediate_only=True)  # the forecast advisory still says 3
    assert str(ev.current_adv(after)) == "3A"
    events = ev.storm_events({before.id: before}, {after.id: after}, T0)
    assert kinds(events) == [EventKind.NEW_ADVISORY]
    assert "3A" in events[0].message


def test_a_classification_change_names_both_classes():
    before = make_storm("3", classification=Classification.TS)
    after = make_storm("4", classification=Classification.HU)
    events = ev.storm_events({before.id: before}, {after.id: after}, T0)
    change = next(e for e in events if e.kind is EventKind.CLASSIFICATION)
    assert change.subject == "TS>HU"


# ---- watches and warnings -----------------------------------------------------------------------------------------


def test_a_new_warning_is_issued_and_a_dropped_watch_is_discontinued():
    storm = make_storm("5")
    before = advisories("4", area("Tropical Storm Watch", "Keys"))
    after = advisories("5", area("Tropical Storm Warning", "Keys"))
    events = ev.watch_warning_events(storm, before, after, T0)
    assert sorted(kinds(events)) == sorted([EventKind.WATCH_WARNING_ISSUED, EventKind.WATCH_WARNING_DISCONTINUED])
    issued = next(e for e in events if e.kind is EventKind.WATCH_WARNING_ISSUED)
    assert issued.key == "al012026|5|ww_issued|TROPICAL STORM WARNING"


def test_changed_places_under_the_same_label_are_a_change_but_their_order_is_not():
    storm = make_storm("5")
    before = advisories("4", area("Tropical Storm Warning", "A", "B"))
    reordered = advisories("5", area("Tropical Storm Warning", "B", "A"))
    wider = advisories("5", area("Tropical Storm Warning", "A", "B", "C"))
    assert ev.watch_warning_events(storm, before, reordered, T0) == []
    assert kinds(ev.watch_warning_events(storm, before, wider, T0)) == [EventKind.WATCH_WARNING_CHANGED]


def test_the_first_advisory_is_a_baseline_not_news():
    storm = make_storm("5")
    after = advisories("5", area("Hurricane Warning", "Miami"))
    assert ev.watch_warning_events(storm, None, after, T0) == []


# ---- discussion and outlook ---------------------------------------------------------------------------------------


def _discussion(number: int) -> Discussion:
    return Discussion("al012026", "TROPICAL STORM", "ANA", AdvNum(number), T0, None, (), (), (), None)


def test_a_discussion_with_a_new_number_is_new():
    storm = make_storm("5")
    old, new = AdvisorySet(discussion=_discussion(4)), AdvisorySet(discussion=_discussion(5))
    assert kinds(ev.discussion_events(storm, old, new, T0)) == [EventKind.NEW_DISCUSSION]
    assert ev.discussion_events(storm, new, new, T0) == []
    assert ev.discussion_events(storm, None, new, T0) == []


def _outlook(issued, invests=()):
    text = OutlookText(None, issued, None, "Atlantic", None, (), "", "", None)
    return Outlook((text,), invests=tuple(invests))


def _invest(number=91):
    fix = BestTrackFix(
        T0, 12.0, -40.0, 25, 1008, "DB", WindRadii(), None, None, None, None, None, None, None, None, None
    )
    return BestTrack("AL", number, (fix,))


def test_a_new_outlook_issue_time_is_news_once():
    first = _outlook(T0)
    assert kinds(ev.outlook_events(None, first, T0)) == [EventKind.NEW_OUTLOOK]
    assert ev.outlook_events(first, _outlook(T0), T0) == []
    assert kinds(ev.outlook_events(first, _outlook(T0 + timedelta(hours=6)), T0)) == [EventKind.NEW_OUTLOOK]


def test_a_new_invest_is_reported_only_against_a_previous_outlook():
    quiet, busy = _outlook(T0), _outlook(T0, [_invest()])
    assert EventKind.NEW_INVEST in kinds(ev.outlook_events(quiet, busy, T0))
    assert EventKind.NEW_INVEST not in kinds(ev.outlook_events(None, busy, T0))
    assert EventKind.NEW_INVEST not in kinds(ev.outlook_events(busy, busy, T0))


# ---- buoys --------------------------------------------------------------------------------------------------------


def test_a_buoy_crossing_34_and_50_kt_fires_both_thresholds_once_each():
    storm = make_storm("5")
    rows = series("41047", obs(T0 - timedelta(hours=1), 30), obs(T0 - timedelta(minutes=30), 52), obs(T0, 45))
    events = ev.buoy_events(storm, "41047", rows, T0)
    assert [e.subject for e in events] == ["41047:34", "41047:50"]
    assert events[1].time == T0 - timedelta(minutes=30)


def test_an_old_crossing_is_history_and_does_not_fire():
    storm = make_storm("5")
    rows = series("41047", obs(T0 - timedelta(hours=10), 70), obs(T0, 20))
    assert ev.buoy_events(storm, "41047", rows, T0) == []


def test_a_buoy_that_just_stopped_reporting_is_silent_and_a_long_dead_one_is_not():
    storm = make_storm("5")
    just_now = series("41001", obs(T0 - timedelta(hours=3), 10))
    assert kinds(ev.buoy_events(storm, "41001", just_now, T0)) == [EventKind.BUOY_SILENT]
    dead = series("41002", obs(T0 - timedelta(days=4), 10))
    assert ev.buoy_events(storm, "41002", dead, T0) == []
    assert ev.buoy_events(storm, "41003", series("41003", obs(T0 - timedelta(minutes=20), 10)), T0) == []


def test_replace_is_not_needed_to_rekey():
    # the key of a buoy event is stable for the same crossing, whichever poll sees it
    storm = make_storm("5")
    rows = series("41047", obs(T0, 40))
    first = ev.buoy_events(storm, "41047", rows, T0)
    later = ev.buoy_events(replace(storm, last_update=T0), "41047", rows, T0 + timedelta(minutes=10))
    assert [e.key for e in first] == [e.key for e in later]


def test_silence_is_judged_from_the_newest_report_the_store_holds():
    storm = make_storm("5")
    stalled = series("41001", obs(T0 - timedelta(hours=3), 10))
    assert kinds(ev.buoy_events(storm, "41001", stalled, T0)) == [EventKind.BUOY_SILENT]
    fresh = obs(T0 - timedelta(minutes=20), 10)  # latest_obs.txt still lists the buoy
    assert ev.buoy_events(storm, "41001", stalled, T0, newest=fresh) == []
