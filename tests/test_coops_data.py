import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from eyewall.coops.data import (
    datagetter_params,
    parse_air_pressure,
    parse_predictions,
    parse_water_level,
    parse_wind,
)
from eyewall.models.obs import Prediction, TidePressure, TideWind, WaterLevelReading

FIXTURES = Path(__file__).parent / "fixtures" / "coops"


def raw(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def gmt(day: int, hour: int, minute: int, month: int = 10) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=UTC)


# --- water level ------------------------------------------------------------------------------------------------


def test_latest_water_level_keeps_the_sigma_flags_and_quality():
    parsed = parse_water_level(raw("water_level_latest.json"))
    assert parsed.items == (WaterLevelReading(gmt(31, 8, 18), 1.995, 0.059, "0,0,0,0", "p"),)
    assert parsed.skipped == 0
    assert parsed.message is None
    assert not parsed.items[0].flagged


def test_a_recent_window_is_newest_first_with_empty_strings_as_gaps():
    parsed = parse_water_level(raw("water_level_recent.json"))
    readings = parsed.items
    assert len(readings) == 720  # 3 days of 6-minute readings
    assert parsed.skipped == 0
    assert [r.time for r in readings] == sorted((r.time for r in readings), reverse=True)
    gaps = [r for r in readings if r.level_ft is None]
    assert [(g.time, g.sigma_ft, g.flags, g.quality) for g in gaps] == [
        (gmt(29, 6, 36), None, "1,1,1,1", "p"),
        (gmt(29, 6, 30), None, "1,1,1,1", "p"),
    ]
    assert all(g.flagged for g in gaps)
    assert readings[-1].time == gmt(28, 8, 24)


def test_a_flag_does_not_blank_the_reading():
    flagged = [
        r for r in parse_water_level(raw("water_level_recent.json")).items if r.flagged and r.level_ft is not None
    ]
    assert len(flagged) == 68  # 70 flagged readings in all, two of them the gaps
    assert all(r.sigma_ft is not None for r in flagged)


def test_the_no_datum_error_is_a_message_not_a_series():
    parsed = parse_water_level(raw("error_no_datum.json"))
    assert parsed.items == ()
    assert parsed.message == "Wrong Datum: Datum cannot be null or empty  ***station=8721604"


# --- predictions ------------------------------------------------------------------------------------------------


def test_high_low_predictions_carry_their_kind_and_run_soonest_first():
    parsed = parse_predictions(raw("predictions_hilo.json"))
    assert parsed.items[:3] == (
        Prediction(gmt(31, 4, 3), 3.646, "H"),
        Prediction(gmt(31, 10, 5), 0.508, "L"),
        Prediction(gmt(31, 16, 42), 4.741, "H"),
    )
    assert [p.kind for p in parsed.items] == ["H", "L", "H", "L", "H", "L", "H"]
    assert parsed.items[-1].time == gmt(1, 17, 44, month=11)


def test_interval_predictions_have_no_kind():
    parsed = parse_predictions(raw("predictions_interval.json"))
    assert len(parsed.items) == 61
    assert parsed.items[0] == Prediction(gmt(31, 0, 0), 1.458, None)
    assert parsed.items[-1].time == gmt(31, 6, 0)
    assert {p.kind for p in parsed.items} == {None}


# --- wind and pressure ------------------------------------------------------------------------------------------


def test_wind_is_knots_with_compass_text_newest_first():
    parsed = parse_wind(raw("wind_recent.json"))
    assert len(parsed.items) == 30
    assert parsed.items[0] == TideWind(gmt(31, 8, 18), 7.58, 69.0, "ENE", 10.89, "0,0")
    assert parsed.items[-1].time == gmt(31, 5, 24)


def test_air_pressure_is_millibars_newest_first():
    parsed = parse_air_pressure(raw("air_pressure_recent.json"))
    assert len(parsed.items) == 30
    assert parsed.items[0] == TidePressure(gmt(31, 8, 18), 1018.4, "0,0,0")
    assert parsed.items[-1] == TidePressure(gmt(31, 5, 24), 1018.9, "0,0,0")


def test_a_product_the_station_does_not_offer_is_an_empty_result_with_noaas_message():
    for parse in (parse_wind, parse_air_pressure, parse_water_level, parse_predictions):
        parsed = parse(raw("wind_no_data.json"))
        assert parsed.items == ()
        assert parsed.message is not None
        assert parsed.message.startswith("No data was found")


# --- odd payloads -----------------------------------------------------------------------------------------------


def test_missing_values_in_every_product_are_none():
    wind = parse_wind(
        json.dumps({"data": [{"t": "2026-10-31 08:00", "s": "", "d": "", "dr": "", "g": "", "f": "1,1"}]})
    )
    assert wind.items == (TideWind(gmt(31, 8, 0), None, None, None, None, "1,1"),)
    pressure = parse_air_pressure(json.dumps({"data": [{"t": "2026-10-31 08:00", "v": ""}]}))
    assert pressure.items == (TidePressure(gmt(31, 8, 0), None, ""),)
    predicted = parse_predictions(json.dumps({"predictions": [{"t": "2026-10-31 08:00", "v": " "}]}))
    assert predicted.items == (Prediction(gmt(31, 8, 0), None, None),)


def test_rows_without_a_usable_time_are_skipped_and_counted():
    payload = {"data": [{"t": "2026-10-31 08:00", "v": "1.0"}, {"v": "2.0"}, {"t": "yesterday", "v": "3"}, "x"]}
    parsed = parse_water_level(json.dumps(payload))
    assert [r.level_ft for r in parsed.items] == [1.0]
    assert parsed.skipped == 3


def test_extra_fields_and_seconds_in_the_time_are_tolerated():
    payload = {"metadata": {"id": "x"}, "data": [{"t": "2026-10-31 08:00:30", "v": "1.5", "extra": [1, 2]}], "more": 1}
    parsed = parse_water_level(json.dumps(payload))
    assert parsed.items[0].time == datetime(2026, 10, 31, 8, 0, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("<html>gateway error</html>", "invalid CO-OPS JSON"),
        ("[1, 2]", "unexpected CO-OPS payload"),
        ("{}", "CO-OPS payload has no 'data'"),
        ('{"data": 5}', "CO-OPS 'data' is not a list"),
        ('{"error": {}}', "CO-OPS reported an error"),
    ],
)
def test_unusable_payloads_give_a_message_and_no_records(text, message):
    parsed = parse_water_level(text)
    assert parsed.items == ()
    assert parsed.message == message


# --- request parameters -----------------------------------------------------------------------------------------


def test_water_level_requests_always_carry_a_datum_and_the_application_name():
    params = datagetter_params("water_level", "8721604")
    assert params == {
        "product": "water_level",
        "station": "8721604",
        "units": "english",
        "time_zone": "gmt",
        "format": "json",
        "application": "eyewall",
        "datum": "MLLW",
        "date": "latest",
    }
    assert datagetter_params("water_level", "9063063", datum="IGLD")["datum"] == "IGLD"
    assert datagetter_params("predictions", "8721604")["datum"] == "MLLW"


def test_wind_and_pressure_requests_have_no_datum():
    assert "datum" not in datagetter_params("wind", "8721604")
    assert "datum" not in datagetter_params("air_pressure", "8721604", date="recent")


def test_a_window_can_be_a_named_range_or_begin_and_hours_in_gmt():
    assert datagetter_params("wind", "8721604", date="recent")["date"] == "recent"
    local = timezone(timedelta(hours=-5))
    params = datagetter_params(
        "predictions", "8721604", interval="hilo", begin=datetime(2026, 10, 31, 0, 0, tzinfo=local), hours=48
    )
    assert (params["begin_date"], params["range"], params["interval"]) == ("20261031 05:00", "48", "hilo")
    assert "date" not in params
    assert datagetter_params("wind", "8721604", end=gmt(31, 8, 0), hours=3)["end_date"] == "20261031 08:00"


def test_interval_only_applies_to_predictions():
    assert "interval" not in datagetter_params("water_level", "8721604", interval="h")


def test_a_named_range_and_a_window_together_are_refused():
    with pytest.raises(ValueError, match="either date or"):
        datagetter_params("wind", "8721604", date="recent", hours=3)


@pytest.mark.parametrize("bad", ["", "87", "8721604&product=x", "../8721604", "8721604 "])
def test_station_ids_that_could_alter_the_request_are_refused(bad):
    with pytest.raises(ValueError, match="not a CO-OPS station id"):
        datagetter_params("wind", bad)
