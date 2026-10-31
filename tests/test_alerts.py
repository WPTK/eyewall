from dataclasses import replace
from datetime import timedelta

from eyewall.config import AlertsConfig
from eyewall.models.events import Event, EventKind, make_key
from eyewall.models.watches import AlertsResult, WatchWarningAlert
from eyewall.state.alerts import SEEN_FILE, AlertEngine, SeenSet, is_wanted, tropical_alerts
from tests.state_support import T0


def event(kind=EventKind.NEW_ADVISORY, adv="5", subject=None) -> Event:
    return Event(kind, make_key(kind, "al012026", adv, subject), "msg", T0, "al012026", adv, subject)


def test_an_event_is_shown_once_and_remembered():
    engine = AlertEngine()
    first = event()
    assert engine.process([first], T0) == [first]
    assert engine.process([first], T0 + timedelta(minutes=5)) == []
    assert engine.log == [first]


def test_the_seen_set_survives_a_restart(tmp_path):
    AlertEngine(state_dir=tmp_path).process([event(), event(adv="6")], T0)
    assert (tmp_path / SEEN_FILE).exists()
    again = AlertEngine(state_dir=tmp_path)
    assert again.process([event(), event(adv="6")], T0) == []
    fresh = event(adv="7")
    assert again.process([fresh], T0) == [fresh]


def test_a_corrupt_seen_file_is_an_empty_set_not_a_crash(tmp_path):
    (tmp_path / SEEN_FILE).write_text("{not json", encoding="utf-8")
    assert len(SeenSet(tmp_path / SEEN_FILE)) == 0


def test_old_keys_are_pruned(tmp_path):
    seen = SeenSet(tmp_path / SEEN_FILE)
    seen.add("old", T0 - timedelta(days=40))
    seen.add("new", T0)
    seen.prune(T0)
    assert "old" not in seen
    assert "new" in seen


def test_the_alert_rules_switch_kinds_off():
    rules = AlertsConfig(new_advisory=False, watches_warnings=False)
    assert not is_wanted(EventKind.NEW_ADVISORY, rules)
    assert not is_wanted(EventKind.NEW_DISCUSSION, rules)
    assert not is_wanted(EventKind.WATCH_WARNING_ISSUED, rules)
    assert is_wanted(EventKind.CLASSIFICATION, rules)
    assert is_wanted(EventKind.NEW_STORM, replace(rules, classification=False))
    engine = AlertEngine(rules)
    assert engine.process([event(), event(EventKind.CLASSIFICATION, subject="TS>HU")], T0)[0].kind is (
        EventKind.CLASSIFICATION
    )


def _alert(event_name: str) -> WatchWarningAlert:
    return WatchWarningAlert(
        id=event_name,
        event=event_name,
        kind=None,
        headline=None,
        area_desc="x",
        severity=None,
        urgency=None,
        certainty=None,
        status=None,
        message_type=None,
        sender_name=None,
        sent=None,
        effective=None,
        onset=None,
        expires=None,
        ends=None,
        description=None,
        instruction=None,
        zones=(),
        same_codes=(),
        rings=(),
    )


def test_non_tropical_event_types_are_dropped_from_the_alerts_feed():
    result = AlertsResult(
        (_alert("Hurricane Warning"), _alert("Extreme Wind Warning"), _alert("Hurricane Force Wind Warning"))
    )
    assert [a.event for a in tropical_alerts(result).alerts] == ["Hurricane Warning"]
