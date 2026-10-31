"""Standard meteorological rows: the one header-driven reader behind every NDBC observation file.

Used for `realtime2/{id}.txt` (45 days), `5day2/{id}_5day.txt`, `latest_obs.txt` (via observation_from_row) and the
historical files, which differ only in their fill values and in having no PTDY column. Winds stay in metres per second
as NDBC reports them (8-minute averages on buoys, 2-minute on C-MAN stations) and are never equated with NHC's 1-minute
knots; convert only for display.
"""

from __future__ import annotations

from eyewall.models.obs import Observation, ObservationSeries
from eyewall.ndbc.table import Row, normalize_station_id, parse_number, parse_time, read_table


def observation_from_row(row: Row) -> Observation | None:
    """An Observation from one table row, or None when the row has no usable date."""
    moment = parse_time(row)
    if moment is None:
        return None
    return Observation(
        time=moment,
        wind_dir_deg=parse_number(row, "WDIR"),
        wind_speed_mps=parse_number(row, "WSPD"),
        gust_mps=parse_number(row, "GST"),
        wave_height_m=parse_number(row, "WVHT"),
        dominant_period_s=parse_number(row, "DPD"),
        average_period_s=parse_number(row, "APD"),
        mean_wave_dir_deg=parse_number(row, "MWD"),
        pressure_hpa=parse_number(row, "PRES"),
        pressure_tendency_hpa=parse_number(row, "PTDY"),
        air_temp_c=parse_number(row, "ATMP"),
        water_temp_c=parse_number(row, "WTMP"),
        dewpoint_c=parse_number(row, "DEWP"),
        visibility_nmi=parse_number(row, "VIS"),
        tide_ft=parse_number(row, "TIDE"),
    )


def parse_stdmet(text: str, station_id: str) -> ObservationSeries:
    """Parse a station file into a series sorted newest first.

    Current files are already newest first and historical ones oldest first; both come out the same way. Rows with
    no usable date are skipped and counted. Text that is not a table at all (an HTML error page) gives an empty
    series with every stray line counted as skipped.
    """
    table = read_table(text)
    observations: list[Observation] = []
    skipped = table.stray_lines
    for row in table.rows:
        observation = observation_from_row(row)
        if observation is None:
            skipped += 1
        else:
            observations.append(observation)
    observations.sort(key=lambda o: o.time, reverse=True)
    return ObservationSeries(normalize_station_id(station_id), tuple(observations), skipped)
