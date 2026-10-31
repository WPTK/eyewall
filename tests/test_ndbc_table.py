from datetime import UTC, datetime

from eyewall.ndbc.table import normalize_station_id, parse_number, parse_text, parse_time, read_table

CURRENT = """\
#YY  MM DD hh mm WDIR WSPD GST  WVHT   DPD   APD MWD   PRES  ATMP  WTMP  DEWP  VIS PTDY  TIDE
#yr  mo dy hr mn degT m/s  m/s     m   sec   sec degT   hPa  degC  degC  degC  nmi  hPa    ft
2026 10 31 07 40  60  8.0 10.0    MM    MM    MM  MM 1018.4  26.0  27.5  22.0   MM   MM    MM
"""


def test_header_gives_the_column_names_and_units_lines_are_ignored():
    table = read_table(CURRENT)
    assert table.header_found
    assert table.columns[:5] == ("YY", "MM", "DD", "hh", "mm")
    assert table.columns[-3:] == ("VIS", "PTDY", "TIDE")
    assert len(table.rows) == 1
    assert table.rows[0]["PRES"] == "1018.4"
    assert table.stray_lines == 0


def test_month_and_minute_are_different_columns():
    row = read_table(CURRENT).rows[0]
    assert parse_time(row) == datetime(2026, 10, 31, 7, 40, tzinfo=UTC)


def test_column_order_does_not_matter():
    swapped = "#YYYY MM DD hh mm PRES WSPD\n2026 10 31 07 40 1010.2 5.5\n"
    row = read_table(swapped).rows[0]
    assert parse_number(row, "PRES") == 1010.2
    assert parse_number(row, "WSPD") == 5.5
    assert parse_number(row, "GST") is None  # a column the file lacks


def test_short_rows_leave_trailing_columns_out_and_long_rows_lose_extras():
    text = "#YY MM DD hh mm WDIR WSPD\n2026 10 31 07 40 60\n2026 10 31 07 30 70 8.0 99 99\n"
    short, long = read_table(text).rows
    assert parse_number(short, "WDIR") == 60
    assert parse_number(short, "WSPD") is None
    assert long == {"YY": "2026", "MM": "10", "DD": "31", "hh": "07", "mm": "30", "WDIR": "70", "WSPD": "8.0"}


def test_old_column_names_are_mapped_to_the_current_ones():
    old = "YY  MM DD hh WD   WSPD  GST  WVHT   DPD   APD MWD  BAR    ATMP  WTMP  DEWP  VIS  TIDE\n97 09 12 06 270  5.0  6.0 99.00 99.00 99.00 999 1011.0  25.0  26.0 999.0 99.0 99.00\n"
    table = read_table(old)
    row = table.rows[0]
    assert table.header_found
    assert parse_number(row, "WDIR") == 270
    assert parse_number(row, "PRES") == 1011.0
    assert parse_time(row) == datetime(1997, 9, 12, 6, 0, tzinfo=UTC)  # two-digit year, no minute column


def test_two_digit_years_below_70_are_this_century():
    row = {"YY": "05", "MM": "01", "DD": "02", "hh": "03", "mm": "04"}
    assert parse_time(row) == datetime(2005, 1, 2, 3, 4, tzinfo=UTC)


def test_mm_blank_junk_and_missing_columns_are_none():
    row = {"A": "MM", "B": "", "C": "n/a", "D": "nan", "E": "inf", "F": "-3.5", "G": "+1.2"}
    assert [parse_number(row, c) for c in "ABCDEFGH"] == [None, None, None, None, None, -3.5, 1.2, None]


def test_every_historical_fill_convention_is_missing():
    fills = {
        "WDIR": "999",
        "WSPD": "99.0",
        "GST": "99.0",
        "WVHT": "99.00",
        "DPD": "99.00",
        "APD": "99.00",
        "MWD": "999",
        "PRES": "9999.0",
        "PTDY": "99.00",
        "ATMP": "999.0",
        "WTMP": "999.0",
        "DEWP": "999.0",
        "VIS": "99.0",
        "TIDE": "99.00",
    }
    for column, token in fills.items():
        assert parse_number({column: token}, column) is None, column
        assert parse_number({column: token}, column, fills=False) is not None, column


def test_a_value_that_merely_resembles_a_fill_in_another_column_is_kept():
    assert parse_number({"ATMP": "99.0"}, "ATMP") == 99.0  # a hot day is not a fill; only 999.0 is
    assert parse_number({"PRES": "999.0"}, "PRES") == 999.0  # a deep low is not a fill; only 9999.0 is
    assert parse_number({"WDIR": "99"}, "WDIR") == 99.0


def test_text_columns_treat_mm_and_na_as_missing():
    row = {"SwD": "ENE", "WWD": "MM", "STEEPNESS": "N/A"}
    assert parse_text(row, "SwD") == "ENE"
    assert parse_text(row, "WWD") is None
    assert parse_text(row, "STEEPNESS") is None
    assert parse_text(row, "absent") is None


def test_impossible_dates_are_none():
    base = {"YY": "2026", "MM": "10", "DD": "31", "hh": "07", "mm": "40"}
    assert parse_time({**base, "MM": "13"}) is None
    assert parse_time({**base, "hh": "MM"}) is None
    assert parse_time({k: v for k, v in base.items() if k != "DD"}) is None


def test_html_or_empty_text_is_not_a_table():
    html = "<!DOCTYPE html>\n<html><body>Not Found</body></html>\n"
    table = read_table(html)
    assert not table.header_found
    assert table.rows == ()
    assert table.stray_lines == 2
    assert not read_table("").header_found


def test_byte_order_mark_and_crlf_are_tolerated():
    text = "﻿" + CURRENT.replace("\n", "\r\n")
    table = read_table(text)
    assert table.header_found
    assert table.rows[0]["TIDE"] == "MM"


def test_station_ids_are_upper_case_without_padding():
    assert normalize_station_id(" trdf1\n") == "TRDF1"
    assert normalize_station_id("4101082") == "4101082"
