"""Parsers for the text products: public advisory (TCP), discussion (TCD), wind probabilities (PWS), outlook (TWO).

All four work on the plain text tgftp serves (or the same text from api.weather.gov or an NHC archive page). They anchor
on headings and labels, not line numbers, and skip what they do not recognise, so a new paragraph in a product does not
break them. A heading that cannot be found raises ParseError; everything else comes back as None or an empty tuple.
"""

from __future__ import annotations

import re
from datetime import datetime

from eyewall.models.advisory import Discussion, DiscussionFix, PublicAdvisory, PublicSummary, WatchWarningText
from eyewall.models.outlook import Chance, OutlookArea, OutlookText
from eyewall.models.watches import WatchWarningArea
from eyewall.models.wind import ProbabilityCell, WindProbabilities, WindProbabilityRow
from eyewall.palette import WatchWarning
from eyewall.providers.base import ParseError
from eyewall.providers.nhc.ids import parse_adv_num
from eyewall.providers.nhc.tcm import split_kind_and_name
from eyewall.providers.nhc.textutil import (
    collapse,
    find_forecaster,
    find_storm_id,
    normalize_newlines,
    numbered_items,
    paragraphs,
)
from eyewall.providers.nhc.times import parse_header_time, resolve_day_time

_TIME_LINE = re.compile(
    r"^[ \t]*\d{3,4}[ \t]+(?:(?:AM|PM)[ \t]+)?[A-Z]{2,4}[ \t]+\w{3}[ \t]+\w{3}[ \t]+\d{1,2}[ \t]+\d{4}[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
_DASHES = re.compile(r"^-{3,}\s*$")
_COORD = r"(?P<lat>\d+(?:\.\d+)?)\s*(?P<ns>[NS])\s+(?P<lon>\d+(?:\.\d+)?)\s*(?P<ew>[EW])"


def _signed(value: str, hemisphere: str) -> float:
    return -float(value) if hemisphere.upper() in {"S", "W"} else float(value)


def _time_after(text: str, start: int) -> tuple[str | None, datetime | None]:
    """The first header time line at or after `start`: its text and the UTC moment."""
    match = _TIME_LINE.search(text, start)
    if match is None:
        return None, None
    line = match.group(0).strip()
    return line, parse_header_time(line)


# ---- watch and warning kinds --------------------------------------------------------------------------------------

_KIND_BY_LABEL: dict[str, WatchWarning] = {
    "tropical storm watch": WatchWarning.TROPICAL_STORM_WATCH,
    "tropical storm warning": WatchWarning.TROPICAL_STORM_WARNING,
    "hurricane watch": WatchWarning.HURRICANE_WATCH,
    "hurricane warning": WatchWarning.HURRICANE_WARNING,
    "storm surge watch": WatchWarning.SURGE_WATCH,
    "storm surge warning": WatchWarning.SURGE_WARNING,
}


def watch_warning_kind(label: str) -> WatchWarning | None:
    """`Tropical Storm Warning` to its palette kind; None for labels eyewall draws no color for."""
    return _KIND_BY_LABEL.get(collapse(label).lower())


# ---- public advisory (TCP) ----------------------------------------------------------------------------------------

_TCP_HEADING = re.compile(
    r"^[ \t]*(?P<title>[A-Za-z][A-Za-z0-9 \-]*?)[ \t]+(?:Intermediate[ \t]+)?Advisory[ \t]+Number[ \t]+"
    r"(?P<num>\d+[ \t]*[A-Za-z]?)(?:\.\.\.[A-Za-z ]+)?[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
_IN_EFFECT = re.compile(r"^(?:An?\s+)?(?P<label>[A-Za-z][A-Za-z \-]*?(?:Watch|Warning))\s+is in effect for\b", re.I)
_NO_WATCHES = re.compile(r"there are no (?:coastal )?(?:watches or warnings|watches|warnings) in effect", re.I)
_SUMMARY_LOCATION = re.compile(rf"LOCATION\.{{3}}{_COORD}")
_SUMMARY_WIND = re.compile(r"MAXIMUM SUSTAINED WINDS\.{3}(?P<mph>\d+)\s*MPH")
_SUMMARY_MOVE = re.compile(
    r"PRESENT MOVEMENT\.{3}(?P<text>[A-Z][A-Z\- ]*?)\s+OR\s+(?P<deg>\d+)\s+DEGREES AT\s+(?P<mph>\d+)\s*MPH"
)
_SUMMARY_PRESSURE = re.compile(
    r"MINIMUM CENTRAL PRESSURE\.{3}(?P<mb>\d+)\s*MB(?:\.{3}(?P<inches>\d+(?:\.\d+)?)\s*INCHES)?"
)
_HAZARD_LABEL = re.compile(r"^(?P<label>[A-Z][A-Z /\-]{2,40}):\s*")
_LAST_ADVISORY = re.compile(r"last (?:public )?advisory|last forecast/advisory", re.IGNORECASE)


def _sections(lines: list[str]) -> tuple[list[tuple[str, list[str]]], int | None]:
    """Split a TCP into (title, body lines) sections marked by a title line over a dashed line.

    Also returns the index of the first section title, where the headlines end.
    """
    starts: list[tuple[int, int]] = []  # (title index, body start)
    for index in range(1, len(lines)):
        if _DASHES.match(lines[index]) and lines[index - 1].strip() and not _DASHES.match(lines[index - 1]):
            starts.append((index - 1, index + 1))
    sections: list[tuple[str, list[str]]] = []
    for position, (title_index, body_start) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        body: list[str] = []
        for line in lines[body_start:end]:
            if line.strip().startswith("$$"):
                break
            body.append(line)
        sections.append((lines[title_index].strip().upper(), body))
    return sections, (starts[0][0] if starts else None)


def _section(sections: list[tuple[str, list[str]]], *prefixes: str) -> str:
    for title, body in sections:
        if any(title.startswith(prefix) for prefix in prefixes):
            return "\n".join(body)
    return ""


def _headlines(block: str) -> tuple[str, ...]:
    found: list[str] = []
    for paragraph in re.split(r"\n\s*\n", block.strip("\n")):
        for part in re.split(r"(?<=\.\.\.)[ \t]*\n[ \t]*(?=\.\.\.)", paragraph):
            text = collapse(part).strip(". ").strip()
            if text:
                found.append(text)
    return tuple(found)


def _parse_summary(text: str) -> PublicSummary:
    location = _SUMMARY_LOCATION.search(text)
    wind = _SUMMARY_WIND.search(text)
    move = _SUMMARY_MOVE.search(text)
    pressure = _SUMMARY_PRESSURE.search(text)
    about = tuple(collapse(line) for line in text.split("\n") if line.strip().upper().startswith("ABOUT "))
    return PublicSummary(
        location_text=collapse(text[location.start() + len("LOCATION...") : location.end()]) if location else None,
        lat=_signed(location["lat"], location["ns"]) if location else None,
        lon=_signed(location["lon"], location["ew"]) if location else None,
        about=about,
        max_wind_mph=int(wind["mph"]) if wind else None,
        movement_text=move["text"] if move else None,
        movement_dir_deg=int(move["deg"]) if move else None,
        movement_speed_mph=int(move["mph"]) if move else None,
        pressure_mb=int(pressure["mb"]) if pressure else None,
        pressure_in=float(pressure["inches"]) if pressure and pressure["inches"] else None,
    )


def parse_watch_warning_text(section: str) -> WatchWarningText:
    """The body of a `WATCHES AND WARNINGS` section."""
    lines = section.split("\n")
    changes: list[str] = []
    in_effect: list[WatchWarningArea] = []
    mode = "intro"
    paragraph: list[str] = []

    def flush_changes() -> None:
        if mode == "changes" and paragraph:
            changes.append(collapse(" ".join(paragraph)))
        paragraph.clear()

    current: tuple[str, list[list[str]]] | None = None
    for line in lines:
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith("CHANGES WITH THIS ADVISORY"):
            flush_changes()
            mode = "changes"
            continue
        if upper.startswith("SUMMARY OF WATCHES AND WARNINGS IN EFFECT"):
            flush_changes()
            mode = "effect"
            continue
        if mode == "changes":
            if stripped:
                paragraph.append(stripped)
            else:
                flush_changes()
            continue
        match = _IN_EFFECT.match(stripped)
        if match is not None:
            if current is not None:
                in_effect.append(_area(current))
            current = (collapse(match["label"]), [])
            mode = "effect"
            continue
        if current is None:
            continue
        if not stripped:
            in_effect.append(_area(current))
            current = None
        elif stripped.startswith("*"):
            current[1].append([stripped.lstrip("* ").strip()])
        elif current[1]:
            current[1][-1].append(stripped)
        else:
            continue
    if current is not None:
        in_effect.append(_area(current))
    flush_changes()
    return WatchWarningText(
        changes=tuple(changes),
        in_effect=tuple(a for a in in_effect if a.areas),
        none_in_effect=_NO_WATCHES.search(section) is not None,
        text="\n".join(line.rstrip() for line in lines).strip("\n"),
    )


def _area(block: tuple[str, list[list[str]]]) -> WatchWarningArea:
    label, items = block
    return WatchWarningArea(label, watch_warning_kind(label), tuple(collapse(" ".join(item)) for item in items))


def _hazards(text: str) -> tuple[tuple[str, str], ...]:
    found: list[tuple[str, list[str]]] = []
    for paragraph in re.split(r"\n\s*\n", text.strip("\n")):
        if not paragraph.strip():
            continue
        match = _HAZARD_LABEL.match(paragraph.strip())
        if match is not None:
            found.append((match["label"], [paragraph.strip()[match.end() :]]))
        elif found:
            found[-1][1].append(paragraph)
        else:
            found.append(("GENERAL", [paragraph]))
    return tuple((label, collapse(" ".join(parts))) for label, parts in found if collapse(" ".join(parts)))


def parse_tcp(text: str | bytes) -> PublicAdvisory:
    """Parse a public advisory. Raises ParseError when there is no `Advisory Number` heading."""
    text = normalize_newlines(text)
    heading = _TCP_HEADING.search(text)
    if heading is None:
        raise ParseError("not a public advisory: no 'Advisory Number' heading")
    kind, name = split_kind_and_name(heading["title"])
    issued_text, issued = _time_after(text, heading.end())
    lines = text.split("\n")
    sections, first_title = _sections(lines)

    headline_block = ""
    if first_title is not None:
        offset = text[: heading.end()].count("\n")
        time_line = _TIME_LINE.search(text, heading.end())
        start = max(offset + 1, text[: time_line.end()].count("\n") + 1) if time_line else offset + 1
        headline_block = "\n".join(lines[start:first_title])

    hazards_text = _section(sections, "HAZARDS AFFECTING LAND")
    marker = re.search(r"KEY MESSAGES\s*:", text, re.IGNORECASE)
    key_messages = numbered_items(text[marker.end() :]) if marker else ()
    next_text = _section(sections, "NEXT ADVISORY")
    watches = parse_watch_warning_text(_section(sections, "WATCHES AND WARNINGS"))
    discussion = "\n\n".join(paragraphs(_section(sections, "DISCUSSION AND OUTLOOK")))
    hazards = tuple((label, body) for label, body in _hazards(hazards_text) if label != "KEY MESSAGES")
    return PublicAdvisory(
        storm_id=find_storm_id(text[heading.start() : heading.end() + 300]),
        kind=kind,
        name=name,
        adv_num=parse_adv_num(heading["num"].replace(" ", "").replace("\t", "")),
        issued=issued,
        issued_text=issued_text,
        headlines=_headlines(headline_block),
        summary=_parse_summary(_section(sections, "SUMMARY OF")),
        watches_warnings=watches,
        discussion=discussion,
        hazards=hazards,
        key_messages=key_messages,
        next_advisory=collapse(next_text),
        forecaster=find_forecaster(text),
        is_last=_LAST_ADVISORY.search(text) is not None,
    )


# ---- discussion (TCD) ---------------------------------------------------------------------------------------------

_TCD_HEADING = re.compile(
    r"^[ \t]*(?P<title>[A-Za-z][A-Za-z0-9 \-]*?)[ \t]+Discussion[ \t]+Number[ \t]+"
    r"(?P<num>\d+[ \t]*[A-Za-z]?)(?:\.\.\.[A-Za-z ]+)?[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
_TCD_TABLE = re.compile(r"^\s*FORECAST POSITIONS AND MAX WINDS\s*$", re.MULTILINE)
_TCD_ROW = re.compile(
    rf"^\s*(?P<hour>INIT|\d+H)\s+(?P<day>\d{{2}})/(?P<hhmm>\d{{4}})Z\s+{_COORD}\s+(?P<kt>\d+)\s*KT\s+(?P<mph>\d+)\s*MPH"
    r"(?P<tail>.*)$"
)
_TCD_DISSIPATED = re.compile(r"^\s*(?P<hour>\d+H)\s+(?P<day>\d{2})/(?P<hhmm>\d{4})Z\W*(?P<tail>[A-Z/\- ]+)\s*$")


def parse_tcd(text: str | bytes) -> Discussion:
    """Parse a forecast discussion. Raises ParseError when there is no `Discussion Number` heading."""
    text = normalize_newlines(text)
    heading = _TCD_HEADING.search(text)
    if heading is None:
        raise ParseError("not a forecast discussion: no 'Discussion Number' heading")
    kind, name = split_kind_and_name(heading["title"])
    issued_text, issued = _time_after(text, heading.end())
    time_line = _TIME_LINE.search(text, heading.end())
    body_start = time_line.end() if time_line else heading.end()
    table = _TCD_TABLE.search(text, body_start)
    body_end = table.start() if table else len(text)
    end_marker = text.find("$$", body_start)
    if end_marker != -1:
        body_end = min(body_end, end_marker)
    body = text[body_start:body_end]

    messages_marker = re.search(r"^[ \t]*KEY MESSAGES[^\n]*:[ \t]*$", body, re.IGNORECASE | re.MULTILINE)
    key_messages: tuple[str, ...] = ()
    narrative = body
    if messages_marker is not None:
        narrative = body[: messages_marker.start()]
        key_messages = numbered_items(body[messages_marker.end() :])

    fixes: list[DiscussionFix] = []
    if table is not None and issued is not None:
        for line in text[table.end() : end_marker if end_marker != -1 else len(text)].split("\n"):
            fix = _tcd_fix(line, issued)
            if fix is not None:
                fixes.append(fix)
    return Discussion(
        storm_id=find_storm_id(text[heading.start() : heading.end() + 300]),
        kind=kind,
        name=name,
        adv_num=parse_adv_num(heading["num"].replace(" ", "").replace("\t", "")),
        issued=issued,
        issued_text=issued_text,
        paragraphs=paragraphs(narrative),
        key_messages=key_messages,
        forecast=tuple(fixes),
        forecaster=find_forecaster(text),
        is_last=_LAST_ADVISORY.search(text) is not None,
    )


def _tcd_fix(line: str, issued: datetime) -> DiscussionFix | None:
    row = _TCD_ROW.match(line)
    if row is not None:
        hour = 0 if row["hour"] == "INIT" else int(row["hour"][:-1])
        tail = row["tail"].strip(" .")
        return DiscussionFix(
            hour=hour,
            valid=resolve_day_time(int(row["day"]), int(row["hhmm"][:2]), int(row["hhmm"][2:]), issued),
            lat=_signed(row["lat"], row["ns"]),
            lon=_signed(row["lon"], row["ew"]),
            wind_kt=int(row["kt"]),
            wind_mph=int(row["mph"]),
            status=tail or None,
        )
    gone = _TCD_DISSIPATED.match(line)
    if gone is not None:
        return DiscussionFix(
            hour=int(gone["hour"][:-1]),
            valid=resolve_day_time(int(gone["day"]), int(gone["hhmm"][:2]), int(gone["hhmm"][2:]), issued),
            lat=None,
            lon=None,
            wind_kt=None,
            wind_mph=None,
            status=gone["tail"].strip() or None,
            dissipated="DISSIPATED" in gone["tail"].upper(),
        )
    return None


# ---- wind speed probabilities (PWS) -------------------------------------------------------------------------------

_PWS_HEADING = re.compile(
    r"^[ \t]*(?P<title>[A-Z][A-Z0-9 \-]*?)[ \t]+WIND SPEED PROBABILITIES[ \t]+NUMBER[ \t]+"
    r"(?P<num>\d+[ \t]*[A-Z]?)(?:\.\.\.[A-Z ]+)?[ \t]*$",
    re.MULTILINE,
)
_PWS_HOURS = re.compile(r"^\s*FORECAST HOUR\s+(?P<hours>(?:\(\s*\d+\s*\)\s*)+)$")
_PWS_ROW = re.compile(r"^(?P<loc>[A-Z0-9][A-Z0-9 .\-/']*?)\s+(?P<kt>34|50|64)\s+(?P<cells>(?:X|\d).*?)\s*$")
_PWS_CONTINUATION = re.compile(r"^\s{8,}(?P<kt>34|50|64)\s+(?P<cells>(?:X|\d).*?)\s*$")
_PWS_CELL = re.compile(r"(?P<onset>X|\d+)(?:\s*\(\s*(?P<cumulative>X|\d+)\s*\))?")


def _percent(token: str) -> int:
    return 0 if token == "X" else int(token)


def _pws_cells(text: str, count: int) -> tuple[ProbabilityCell | None, ...]:
    cells: list[ProbabilityCell | None] = []
    for match in _PWS_CELL.finditer(text):
        onset = _percent(match["onset"])
        cumulative = _percent(match["cumulative"]) if match["cumulative"] else onset
        cells.append(ProbabilityCell(onset, cumulative))
    cells = cells[:count]
    cells.extend([None] * (count - len(cells)))
    return tuple(cells)


def parse_pws(text: str | bytes) -> WindProbabilities:
    """Parse a wind speed probability product. The table may be empty (a final advisory prints none)."""
    text = normalize_newlines(text)
    heading = _PWS_HEADING.search(text)
    if heading is None:
        raise ParseError("not a wind speed probability product: no heading")
    _, name = split_kind_and_name(heading["title"])
    time_line = re.search(r"^\s*\d{3,4}\s+UTC\s+\w{3}\s+\w{3}\s+\d{1,2}\s+\d{4}", text[heading.end() :], re.MULTILINE)
    issued = parse_header_time(time_line.group(0)) if time_line else None

    hours: tuple[int, ...] = ()
    rows: list[WindProbabilityRow] = []
    skipped = 0
    location = ""
    for line in text[heading.end() :].split("\n"):
        header = _PWS_HOURS.match(line)
        if header is not None:
            hours = tuple(int(h) for h in re.findall(r"\((\s*\d+\s*)\)", header["hours"]))
            continue
        if not hours:
            continue
        row = _PWS_ROW.match(line)
        if row is not None:
            location = row["loc"].strip()
            rows.append(WindProbabilityRow(location, int(row["kt"]), _pws_cells(row["cells"], len(hours))))
            continue
        more = _PWS_CONTINUATION.match(line)
        if more is not None and location:
            rows.append(WindProbabilityRow(location, int(more["kt"]), _pws_cells(more["cells"], len(hours))))
        elif re.search(r"\d\s*\(\s*(?:X|\d+)\s*\)", line):
            skipped += 1
    return WindProbabilities(
        storm_id=find_storm_id(text[heading.start() : heading.end() + 300]),
        name=name,
        adv_num=parse_adv_num(heading["num"].replace(" ", "").replace("\t", "")),
        issued=issued,
        forecast_hours=hours,
        rows=tuple(rows),
        skipped=skipped,
    )


# ---- tropical weather outlook (TWO) -------------------------------------------------------------------------------

_TWO_CHANCE = re.compile(
    r"^\*\s*Formation chance through\s+(?P<span>\d+)\s+(?P<unit>hours?|days?)\W+"
    r"(?P<risk>low|medium|high)\W+(?P<percent>near\s+0|\d+)\s*percent",
    re.IGNORECASE,
)
_TWO_HEADER = re.compile(
    r"^(?:(?P<number>\d+)\.\s+)?(?P<title>[^:*]{2,140}?)(?:\s*\((?P<invest>[A-Z]{2}\d{2})\))?:\s*$"
)
_TWO_OFFICE = re.compile(r"^NWS .*(?:Hurricane Center|Weather Service).*$", re.IGNORECASE)


def _chance(match: re.Match[str]) -> Chance:
    percent = 0 if match["percent"].lower().startswith("near") else int(match["percent"])
    return Chance(match["risk"].lower(), percent)


def parse_two(text: str | bytes) -> OutlookText:
    """Parse a tropical weather outlook: its areas with 48 hour and 7 day chances, and the active systems paragraph."""
    text = normalize_newlines(text)
    # A special outlook replaces the routine one in the same file and product header, under a longer heading.
    start = re.search(r"^\s*(?:Special\s+)?Tropical Weather Outlook\s*$", text, re.IGNORECASE | re.MULTILINE)
    if start is None:
        raise ParseError("not a tropical weather outlook: no 'Tropical Weather Outlook' heading")
    lines = text[start.end() :].split("\n")
    office = next((line.strip() for line in lines[:6] if _TWO_OFFICE.match(line.strip())), None)
    issued_text, issued = _time_after(text, start.end())

    region: str | None = None
    summary: list[str] = []
    notes: list[str] = []
    active: list[str] = []
    areas: list[OutlookArea] = []
    current: dict[str, object] | None = None
    section = "summary"  # summary | active | area | notes
    previous_blank = True
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("$$") or re.match(r"^Forecasters?\s", stripped):
            break
        if region is None and stripped.lower().startswith("for ") and stripped.endswith(":"):
            region = stripped.rstrip(":")
            previous_blank = False
            continue
        if _TIME_LINE.match(line) or (office and stripped == office) or stripped.lower().startswith("issued by"):
            continue
        chance = _TWO_CHANCE.match(stripped)
        if chance is not None and current is not None:
            hours = int(chance["span"]) * (24 if chance["unit"].lower().startswith("day") else 1)
            if hours == 48:
                current["chance_48h"] = _chance(chance)
            elif hours == 7 * 24:
                current["chance_7d"] = _chance(chance)
            section = "notes"
            previous_blank = False
            continue
        header = _TWO_HEADER.match(stripped) if previous_blank and stripped and region is not None else None
        if header is not None and not stripped.lower().startswith(("for ", "forecaster")):
            if current is not None:
                areas.append(_outlook_area(current))
                current = None
            if header["title"].strip().lower() == "active systems":
                section = "active"
            else:
                section = "area"
                current = {
                    "number": int(header["number"]) if header["number"] else None,
                    "title": header["title"].strip(),
                    "invest_id": header["invest"],
                    "lines": [],
                }
            previous_blank = False
            continue
        previous_blank = not stripped
        if not stripped and section in {"summary", "notes"} and not (summary or notes):
            continue
        if section == "summary":
            summary.append(stripped)
        elif section == "active":
            active.append(stripped)
        elif section == "area" and current is not None:
            lines_list = current["lines"]
            assert isinstance(lines_list, list)
            lines_list.append(stripped)
        else:
            notes.append(stripped)
    if current is not None:
        areas.append(_outlook_area(current))
    return OutlookText(
        office=office,
        issued=issued,
        issued_text=issued_text,
        region=region,
        active_systems=collapse(" ".join(active)) or None,
        areas=tuple(areas),
        summary="\n\n".join(paragraphs("\n".join(summary))),
        notes="\n\n".join(paragraphs("\n".join(notes))),
        forecaster=find_forecaster(text),
    )


def _outlook_area(fields: dict[str, object]) -> OutlookArea:
    lines = fields["lines"]
    assert isinstance(lines, list)
    number = fields["number"]
    invest = fields["invest_id"]
    c48 = fields.get("chance_48h")
    c7 = fields.get("chance_7d")
    return OutlookArea(
        number=number if isinstance(number, int) else None,
        title=str(fields["title"]),
        invest_id=invest if isinstance(invest, str) else None,
        description=collapse(" ".join(lines)),
        chance_48h=c48 if isinstance(c48, Chance) else None,
        chance_7d=c7 if isinstance(c7, Chance) else None,
    )
