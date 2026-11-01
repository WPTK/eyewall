"""README claims as data: every key, flag and documented behaviour in the README maps to the proof that covers it.

`test_claims_traceability` parses the README and fails when a key row or a command-line flag appears there that this table
does not know, or when a claim's proof does not exist. A proof is an inventory item id (`key:storm:left`; `*` matches any
tail, so `click:crumb:*` means any crumb), or a test as `file.py::test_name`.

Each entry is: claim id -> (one behaviour with its expected result, proofs).
"""

from __future__ import annotations

CLI = "tests/uat/test_cli_claims.py"
MATRIX = "tests/uat/inventory/test_matrix.py"
BOUND = "tests/uat/test_boundaries.py"

# README key token -> (behaviour and expected result, proofs)
KEYS: dict[str, tuple[str, tuple[str, ...]]] = {
    "?": ("Help: every key. Opens the help dialog", ("key:main:question_mark", "key:help:question_mark")),
    "Ctrl+P": ("The menu opens and lists screens, actions, storms and stations", ("key:main:ctrl+p", "palette:Open storm")),
    "Esc": ("Go back one screen, close a dialog, leave the full-screen map", ("key:storm:escape", "key:help:escape", "key:main:escape")),
    "Backspace": ("Go back one screen", ("key:storm:backspace",)),
    "q": ("Quit from the first screen only", ("key:main:q", "key:storm:q")),
    "m": ("Go to the map from any screen", ("key:storm:m",)),
    "D": ("Feed health dialog opens", ("key:main:D",)),
    "/": ("Find a buoy or tide gauge opens the search", ("key:main:slash", "palette:Find station")),
    "g": ("Pictures for the selected storm", ("key:main:g", "key:storm:g")),
    "A": ("The alert log opens and A again goes back", ("key:main:A", "key:alerts:A")),
    "S": ("Settings dialog opens", ("key:main:S",)),
    "r": ("Refresh every feed now (a toast says so); charts or readings on a station", ("key:main:r", "key:station:r")),
    "u": ("Cycle the units", ("key:main:u",)),
    "j": ("Next storm becomes the selected one", ("key:main:j", "claim:link-storm-selection-visible")),
    "k": ("Previous storm becomes the selected one", ("key:main:k",)),
    "Enter": ("Open the selected storm's page", ("key:main:enter", "key:buoys:enter")),
    "1": ("Atlantic only", ("key:main:1",)),
    "2": ("East Pacific only", ("key:main:2",)),
    "3": ("Central Pacific only", ("key:main:3",)),
    "a": ("All basins", ("key:main:a",)),
    "b": ("Buoys and gauges near the storm", ("key:main:b", "key:storm:b")),
    "t": ("The NHC text for the storm", ("key:main:t", "key:storm:t")),
    "O": ("The outlook text", ("key:main:O",)),
    "M": ("Full-screen map", ("key:main:M",)),
    "R": ("Replay Hurricane Erin when nothing is active", ("key:main:R",)),
    "+": ("Zoom in", ("key:main:plus",)),
    "-": ("Zoom out", ("key:main:minus",)),
    "f": ("Fit the storm; on stations follow or stop following", ("key:main:f", "key:buoys:f", "key:station:f")),
    "c": ("Center on the storm", ("key:main:c",)),
    "n": ("Step to the next storm, buoy or gauge", ("key:main:n",)),
    "N": ("Step to the previous storm, buoy or gauge", ("key:main:N",)),
    "l": ("Map layers dialog", ("key:main:l",)),
    "p": ("The chance of storm-force wind at named places", ("key:storm:p",)),
    "Left": ("Previous storm (Storm page) or product (NHC text)", ("key:storm:left", "key:text:left")),
    "Right": ("Next storm (Storm page) or product (NHC text)", ("key:storm:right", "key:text:right")),
    "s": ("Change the order of the stations", ("key:buoys:s",)),
    "Tab": ("Switch tabs (buoys); show the next chart (station)", ("key:buoys:tab", "key:station:tab")),
    "h": ("Station hours 24, 48 or 72", ("key:station:h",)),
    "i": ("How buoy winds differ from the storm's", ("key:station:i",)),
    "o": ("Open the picture's address in a browser", ("key:graphics:o",)),
    "y": ("Copy the picture's address", ("key:graphics:y",)),
    "[": ("Step back through a loop or an advisory", ("key:graphics:left_square_bracket",)),
    "]": ("Step forward through a loop or an advisory", ("key:graphics:right_square_bracket",)),
    "Space": ("Play or pause a loop or the replay", ("key:graphics:space", "key:main:space")),
    "<": ("Replay slower", ("key:main:less_than_sign",)),
    ">": ("Replay faster", ("key:main:greater_than_sign",)),
}
# README tokens that name the same key as another row, or that are not one key
KEY_ALIASES = {"Page Up": "Left", "Page Down": "Left", "Arrow keys": "Left"}

FLAGS: dict[str, tuple[str, tuple[str, ...]]] = {
    "--demo": ("Replays the bundled Erin recording", (f"{CLI}::test_demo_summary",)),
    "--replay": ("Replays a recording of your own; a missing folder is a clean error", (f"{CLI}::test_replay_missing_dir",)),
    "--basin": ("Only that basin; a bad basin is a usage error", (f"{CLI}::test_basin_filter", f"{CLI}::test_bad_basin")),
    "--summary": ("Prints plain sentences and exits", (f"{CLI}::test_demo_summary",)),
    "--glyphs": ("Plain symbols; a bad value is a usage error", (f"{CLI}::test_glyphs_ascii", f"{CLI}::test_bad_glyphs")),
    "--headless": ("No interface; prints events", (f"{CLI}::test_headless_until",)),
    "--until": ("Stops the headless run at the given time", (f"{CLI}::test_headless_until",)),
    "--config": ("Reads the settings file at PATH", (f"{CLI}::test_config_path",)),
    "--no-config": ("Ignores the settings file", (f"{CLI}::test_no_config",)),
    "--state-dir": ("Where seen events are kept", (f"{CLI}::test_state_dir",)),
    "--version": ("Prints the version", (f"{CLI}::test_version",)),
    "--help": ("Lists every flag", (f"{CLI}::test_help_lists_flags",)),
}

BEHAVIOURS: dict[str, tuple[str, tuple[str, ...]]] = {
    "click-storm": ("Clicking a storm on the map opens its page and the storm stays marked", ("click:mark:storm",)),
    "click-station": ("Clicking a buoy or gauge on the map opens its page and it stays marked", ("click:mark:buoy", "click:mark:gauge")),
    "click-chooser": ("Overlapping marks open a chooser", ("click:mark:chooser",)),
    "click-card-link": ("A card's open > link opens the storm", ("click:link:main:side:open:storm",)),
    "click-list-row": ("A row in a list opens the station", ("click:row:buoys:*",)),
    "click-breadcrumb": ("The breadcrumb goes back", ("click:crumb:*",)),
    "click-footer": ("Every key in the footer can be clicked", ("click:footer:*",)),
    "click-health-slot": ("The feed-health slot opens feed health", ("click:slot:*",)),
    "drag-pan": ("Drag the map to pan it", ("click:mark:drag",)),
    "wheel-zoom": ("The wheel zooms", ("click:mark:wheel",)),
    "hover-name": ("Hovering a mark names it", ("click:mark:hover",)),
    "menu-everything": ("The menu lists every screen, action, storm and station", ("palette:Open storm", "palette:Open buoys and gauges")),
    "footer-ends-help": ("The footer shows keys that work and ends with ? help", (f"{MATRIX}::test_matrix_rules",)),
    "map-first": ("The map is the first screen at every terminal size", (f"{MATRIX}::test_matrix_rules",)),
    "mark-row-linkage": ("Clicking a mark selects its row; selecting a row marks it", ("claim:link-mark-to-row", "claim:link-row-to-mark")),
    "station-show-on-map": ("m on a station shows it on the map", ("claim:link-station-to-mark",)),
    "too-small-message": ("A terminal under 60x16 gets a message that says what size is needed", (f"{BOUND}::test_too_small_terminal",)),
    "offline-honest": ("Offline, the screens say so and never show a quiet day", (f"{BOUND}::test_offline_recovers", f"{MATRIX}::test_matrix_rules")),
    "no-colour": ("NO_COLOR and ascii glyphs leave every screen readable", (f"{BOUND}::test_no_color_and_ascii",)),
    "search-no-hit": ("Searching for nothing finds nothing without an error", (f"{BOUND}::test_search_no_match",)),
}
LINK_ITEMS = (
    "claim:link-storm-selection-visible",
    "claim:link-storm-selection-sticks",
    "claim:link-mark-to-row",
    "claim:link-row-to-mark",
    "claim:link-station-to-mark",
)


def items() -> set[str]:
    """The claim items the checks themselves report (the linkage claims)."""
    return set(LINK_ITEMS)


def table() -> dict[str, tuple[str, tuple[str, ...]]]:
    out = {f"key-{k.strip()}": v for k, v in KEYS.items()}
    out |= {f"flag-{k}": v for k, v in FLAGS.items()}
    out |= BEHAVIOURS
    return out
