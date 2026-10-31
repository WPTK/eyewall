"""Parser for the forecast/advisory text (TCM, WMO headings WTNT2x, WTPZ2x, WTPA2x).

The TCM is the numeric truth behind the map, so it is parsed by anchoring on the labels NHC prints, not on positions.
A line a storm does not need is simply absent (the 64 kt radii of a tropical storm, every radius of a remnant low) and
comes back as None. What the parser relies on:

- The heading `HURRICANE ERIN FORECAST/ADVISORY NUMBER  30`, the `NWS ... AL052025` line and a
  `2100 UTC MON AUG 18 2025` time line near the top.
- `... CENTER LOCATED NEAR 24.0N  71.3W AT 18/2100Z`, the first such line (the later `REPEAT...` line is ignored).
- `FORECAST VALID 19/0600Z 24.9N  71.9W` and `OUTLOOK VALID` blocks, each with `MAX WIND` and radii lines. A fix can
  end in `...INLAND` or `...POST-TROP/REMNT LOW`, or be `FORECAST VALID 01/0600Z...DISSIPATED` with no position.
- Longitudes end in W or E; near the dateline both appear in one product.

Forecast hours count from the synoptic time, the `AT dd/hhmmZ CENTER WAS LOCATED NEAR` line, three hours before the
advisory.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from eyewall.models.forecast import ForecastAdvisory, ForecastFix, PriorFix
from eyewall.models.storm import AdvNum
from eyewall.models.wind import QuadrantRadii, SeasRadii, WindRadii
from eyewall.providers.base import ParseError
from eyewall.providers.nhc.ids import parse_adv_num
from eyewall.providers.nhc.times import parse_header_time, resolve_day_time

# Longest first, so POTENTIAL TROPICAL CYCLONE is not read as TROPICAL CYCLONE.
_KINDS = (
    "POTENTIAL TROPICAL CYCLONE",
    "POTENTIAL TROP CYCLONE",
    "POST-TROPICAL CYCLONE",
    "SUBTROPICAL DEPRESSION",
    "SUBTROPICAL STORM",
    "TROPICAL DEPRESSION",
    "TROPICAL STORM",
    "SUPER TYPHOON",
    "REMNANTS OF",
    "HURRICANE",
    "TYPHOON",
)

_HEADING = re.compile(
    r"^\s*(?P<title>[A-Z][A-Z0-9 /\-]*?)\s+FORECAST/ADVISORY NUMBER\s+(?P<num>\d+\s*[A-Z]?)\s*$", re.MULTILINE
)
_STORM_ID = re.compile(r"\b(?P<id>(?:AL|EP|CP)\d{6})\b")
_UTC_LINE = re.compile(r"^\s*\d{3,4}\s+UTC\s+\w{3}\s+\w{3}\s+\d{1,2}\s+\d{4}", re.MULTILINE)
_COORD = r"(?P<lat>\d+(?:\.\d+)?)\s*(?P<ns>[NS])\s+(?P<lon>\d+(?:\.\d+)?)\s*(?P<ew>[EW])"
_CENTER = re.compile(
    rf"^\s*(?P<kind>[A-Z][A-Z\- /]*?)?\s*CENTER LOCATED NEAR\s+{_COORD}\s+AT\s+(?P<day>\d{{2}})/(?P<hhmm>\d{{4}})Z",
    re.MULTILINE,
)
_PRIOR = re.compile(rf"\bAT\s+(?P<day>\d{{2}})/(?P<hhmm>\d{{4}})Z\s+CENTER WAS LOCATED NEAR\s+{_COORD}", re.MULTILINE)
_ACCURACY = re.compile(r"POSITION ACCURATE WITHIN\s+(\d+)\s*NM")
_MOVEMENT = re.compile(
    r"PRESENT MOVEMENT TOWARD THE\s+(?P<text>[A-Z][A-Z\- ]*?)\s+OR\s+(?P<deg>\d+)\s+DEGREES AT\s+(?P<speed>\d+)\s*KT"
)
_PRESSURE = re.compile(r"ESTIMATED MINIMUM CENTRAL PRESSURE\s+(\d+)\s*MB")
_EYE = re.compile(r"EYE DIAMETER\s+(\d+)\s*NM")
_WINDS = re.compile(r"MAX SUSTAINED WINDS\s+(?P<wind>\d+)\s*KT(?:\s+WITH GUSTS TO\s+(?P<gust>\d+)\s*KT)?")
_NEXT = re.compile(r"NEXT ADVISORY AT\s+(?P<day>\d{2})/(?P<hhmm>\d{4})Z")
_FIX = re.compile(r"^\s*(?P<which>FORECAST|OUTLOOK) VALID\s+(?P<day>\d{2})/(?P<hhmm>\d{4})Z(?P<rest>.*)$")
_FIX_REST = re.compile(rf"^\s*{_COORD}(?P<tail>.*)$")
_MAX_WIND = re.compile(r"^\s*MAX WIND\s+(?P<wind>\d+)\s*KT(?:\W+GUSTS\s+(?P<gust>\d+)\s*KT)?")
_RADII = re.compile(r"^\s*(?P<kt>\d+)\s*KT\.{2,}\s*(?P<body>.*?)\s*$")
_SEAS = re.compile(r"^\s*(?P<height>\d+)\s*(?P<unit>M|FT)\s+SEAS\.{2,}\s*(?P<body>.*?)\s*$")
_QUADRANT = re.compile(r"(\d+)\s*(NE|SE|SW|NW)")
_BLOCK_END = re.compile(r"^\s*(EXTENDED OUTLOOK|REQUEST FOR|NEXT ADVISORY|INTERMEDIATE|\$\$|THIS IS THE LAST|NNNN)")


def _signed(value: str, hemisphere: str) -> float:
    return -float(value) if hemisphere in {"S", "W"} else float(value)


def split_kind_and_name(title: str) -> tuple[str, str | None]:
    """`HURRICANE ERIN` to (`HURRICANE`, `ERIN`); `Remnants Of Vance` to (`REMNANTS OF`, `Vance`).

    The kind comes back upper case whatever the product's case; the name keeps its case. A title that starts with no
    known kind comes back whole as the kind, with no name.
    """
    text = " ".join(title.split())
    upper = text.upper()
    for kind in _KINDS:
        if upper == kind:
            return kind, None
        if upper.startswith(kind + " "):
            return kind, text[len(kind) + 1 :]
    return upper, None


def _quadrants(body: str) -> QuadrantRadii:
    found = {quadrant: int(value) for value, quadrant in _QUADRANT.findall(body)}
    return QuadrantRadii(found.get("NE"), found.get("SE"), found.get("SW"), found.get("NW"))


def _read_radii(lines: list[str]) -> tuple[WindRadii, SeasRadii | None]:
    """The 34, 50 and 64 kt lines and the seas line inside one block of text."""
    by_threshold: dict[int, QuadrantRadii] = {}
    seas: SeasRadii | None = None
    for line in lines:
        radii = _RADII.match(line)
        if radii is not None:
            by_threshold[int(radii["kt"])] = _quadrants(radii["body"])
            continue
        sea = _SEAS.match(line)
        if sea is not None and seas is None:
            seas = SeasRadii(int(sea["height"]), sea["unit"], _quadrants(sea["body"]))
    return WindRadii(by_threshold.get(34), by_threshold.get(50), by_threshold.get(64)), seas


def _parse_fix(header: re.Match[str], block: list[str], issued: datetime, synoptic: datetime) -> ForecastFix | None:
    valid = resolve_day_time(int(header["day"]), int(header["hhmm"][:2]), int(header["hhmm"][2:]), issued)
    if valid is None:
        return None
    tau = round((valid - synoptic) / timedelta(hours=1))
    outlook = header["which"] == "OUTLOOK"
    rest = header["rest"]
    position = _FIX_REST.match(rest)
    if position is None:
        dissipated = "DISSIPATED" in rest.upper()
        status = None if dissipated else (rest.strip(". ") or None)
        return ForecastFix(tau, valid, None, None, None, None, WindRadii(), status, dissipated, outlook)
    wind_gust = next((m for m in map(_MAX_WIND.match, block) if m is not None), None)
    radii, _ = _read_radii(block)
    status = position["tail"].strip(" .") or None
    return ForecastFix(
        tau,
        valid,
        _signed(position["lat"], position["ns"]),
        _signed(position["lon"], position["ew"]),
        int(wind_gust["wind"]) if wind_gust else None,
        int(wind_gust["gust"]) if wind_gust and wind_gust["gust"] else None,
        radii,
        status,
        False,
        outlook,
    )


def parse_tcm(text: str | bytes) -> ForecastAdvisory:
    """Parse a forecast/advisory. Raises ParseError when the text is not one (no heading or no center line)."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    heading = _HEADING.search(text)
    center = _CENTER.search(text)
    if heading is None or center is None:
        raise ParseError("not a forecast/advisory: no heading or no CENTER LOCATED NEAR line")
    top = text[: heading.end() + 400]
    time_line = _UTC_LINE.search(text, heading.end())
    issued = parse_header_time(time_line.group(0)) if time_line else None
    if issued is None:
        raise ParseError("forecast/advisory has no UTC issue time")

    kind, name = split_kind_and_name(heading["title"])
    storm_id_match = _STORM_ID.search(top)
    lines = text.split("\n")

    prior_match = _PRIOR.search(text)
    prior: PriorFix | None = None
    if prior_match is not None:
        when = resolve_day_time(
            int(prior_match["day"]), int(prior_match["hhmm"][:2]), int(prior_match["hhmm"][2:]), issued
        )
        if when is not None:
            prior = PriorFix(
                when, _signed(prior_match["lat"], prior_match["ns"]), _signed(prior_match["lon"], prior_match["ew"])
            )
    synoptic = prior.time if prior is not None else issued - timedelta(hours=3)

    fix_starts = [(i, m) for i, line in enumerate(lines) if (m := _FIX.match(line)) is not None]
    head_end = fix_starts[0][0] if fix_starts else len(lines)
    head = "\n".join(lines[:head_end])
    radii, seas = _read_radii(lines[:head_end])

    fixes: list[ForecastFix] = []
    for position, (start, match) in enumerate(fix_starts):
        stop = fix_starts[position + 1][0] if position + 1 < len(fix_starts) else len(lines)
        block: list[str] = []
        for line in lines[start + 1 : stop]:
            if _BLOCK_END.match(line):
                break
            block.append(line)
        fix = _parse_fix(match, block, issued, synoptic)
        if fix is not None:
            fixes.append(fix)

    movement = _MOVEMENT.search(head)
    winds = _WINDS.search(head)
    accuracy = _ACCURACY.search(head)
    pressure = _PRESSURE.search(head)
    eye = _EYE.search(head)
    next_match = _NEXT.search(text)
    next_advisory = (
        resolve_day_time(int(next_match["day"]), int(next_match["hhmm"][:2]), int(next_match["hhmm"][2:]), issued)
        if next_match
        else None
    )
    adv_num: AdvNum | None = parse_adv_num(heading["num"].replace(" ", ""))

    return ForecastAdvisory(
        storm_id=storm_id_match["id"].lower() if storm_id_match else None,
        kind=kind,
        name=name,
        adv_num=adv_num,
        issued=issued,
        synoptic=synoptic,
        center_kind=center["kind"].strip() if center["kind"] else None,
        lat=_signed(center["lat"], center["ns"]),
        lon=_signed(center["lon"], center["ew"]),
        position_accuracy_nm=int(accuracy[1]) if accuracy else None,
        movement_text=movement["text"] if movement else None,
        movement_dir_deg=int(movement["deg"]) if movement else None,
        movement_speed_kt=int(movement["speed"]) if movement else None,
        pressure_mb=int(pressure[1]) if pressure else None,
        eye_diameter_nm=int(eye[1]) if eye else None,
        max_wind_kt=int(winds["wind"]) if winds else None,
        gust_kt=int(winds["gust"]) if winds and winds["gust"] else None,
        radii=radii,
        seas=seas,
        prior=prior,
        fixes=tuple(fixes),
        is_final="THIS IS THE LAST FORECAST/ADVISORY" in text,
        next_advisory=next_advisory,
    )
