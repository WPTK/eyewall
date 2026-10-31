"""`{id}_5day.spec`: the wave summary, with swell and wind-wave parts reported separately.

Rows come every half hour or hour on stations that measure waves. Directions are compass text such as ENE, printed by
NDBC itself; steepness is a word (STEEP, AVERAGE, SWELL, N/A when absent). MM and N/A become None.
"""

from __future__ import annotations

from eyewall.models.obs import Parsed, WaveSummary
from eyewall.ndbc.table import parse_number, parse_text, parse_time, read_table


def parse_spec(text: str) -> Parsed[WaveSummary]:
    """Parse a .spec file by header name, newest first. Rows with no usable date are skipped and counted."""
    table = read_table(text)
    waves: list[WaveSummary] = []
    skipped = table.stray_lines
    for row in table.rows:
        moment = parse_time(row)
        if moment is None:
            skipped += 1
            continue
        waves.append(
            WaveSummary(
                time=moment,
                wave_height_m=parse_number(row, "WVHT"),
                swell_height_m=parse_number(row, "SwH"),
                swell_period_s=parse_number(row, "SwP"),
                wind_wave_height_m=parse_number(row, "WWH"),
                wind_wave_period_s=parse_number(row, "WWP"),
                swell_direction=parse_text(row, "SwD"),
                wind_wave_direction=parse_text(row, "WWD"),
                steepness=parse_text(row, "STEEPNESS"),
                average_period_s=parse_number(row, "APD"),
                mean_wave_dir_deg=parse_number(row, "MWD"),
            )
        )
    waves.sort(key=lambda w: w.time, reverse=True)
    message = None if table.header_found else "not an NDBC wave table"
    return Parsed(tuple(waves), skipped, message)
