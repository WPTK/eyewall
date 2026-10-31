"""latest_obs.txt: every station's newest observation in one file (about 100 KB, observations under 2 hours old).

The row carries the station id and position in front of the usual measurements. Waves are mostly MM here; the station
files hold them. PTDY is only filled on the hour. Station ids are upper case in this file, including C-MAN stations.
"""

from __future__ import annotations

from eyewall.models.obs import LatestObservation, Parsed
from eyewall.ndbc.stdmet import observation_from_row
from eyewall.ndbc.table import normalize_station_id, parse_number, read_table


def parse_latest_obs(text: str) -> Parsed[LatestObservation]:
    """Parse latest_obs.txt by header name. Rows without a station id or a date are skipped and counted."""
    table = read_table(text)
    found: list[LatestObservation] = []
    skipped = table.stray_lines
    for row in table.rows:
        observation = observation_from_row(row)
        station_id = normalize_station_id(row.get("STN", ""))
        if observation is None or not station_id:
            skipped += 1
            continue
        found.append(LatestObservation(station_id, parse_number(row, "LAT"), parse_number(row, "LON"), observation))
    message = None if table.header_found else "not an NDBC observation table"
    return Parsed(tuple(found), skipped, message)
