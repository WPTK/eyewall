"""The settings screen: poll intervals, units, basins, nearby radii, alert rules and the glyph set.

The fields are turned back into the shape of the TOML file and run through `config.parse_config`, the same validation
the file gets on load, so the screen can never save what the loader would reject. Anything it reports is shown and
nothing is saved until every field is valid.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Select, Static, Switch

from eyewall.config import BASINS, GLYPH_SETS, Config, parse_config, to_dict
from eyewall.units import PRESETS

if TYPE_CHECKING:
    from eyewall.app import EyewallApp

POLL_FIELDS = ("storms", "outlook", "alerts", "buoys", "tides", "satellite")
NEARBY_FIELDS = (
    ("radius_now_nm", "Radius around the storm (nm)"),
    ("radius_track_nm", "Radius around the forecast track (nm)"),
    ("track_hours", "Forecast track length (hours)"),
    ("max_stations", "Most stations per storm"),
)
ALERT_FIELDS = (
    ("new_advisory", "New advisories and discussions"),
    ("classification", "Classification changes"),
    ("watches_warnings", "Watches and warnings"),
    ("outlook", "Outlook and new invests"),
    ("buoy_thresholds", "Buoy wind thresholds and silence"),
    ("bell", "Terminal bell with a toast"),
)
BASIN_NAMES = {"AL": "Atlantic", "EP": "East Pacific", "CP": "Central Pacific"}


def number_or_text(text: str) -> int | float | str:
    """A field's text as a number when it is one (a whole number stays an int, which the integer fields require);
    otherwise the text, which `parse_config` reports as not a number."""
    text = text.strip()
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def build_config(current: Config, fields: Mapping[str, Any]) -> tuple[Config, list[str]]:
    """The config after the edits in `fields`, and the problems found. Sections the screen does not edit (the
    watchlists, the map layers, the other poll settings) carry over from `current`."""
    data = to_dict(current)
    data["poll"].update({key: number_or_text(str(fields[f"poll.{key}"])) for key in POLL_FIELDS})
    data["units"]["preset"] = fields["units.preset"]
    data["map"]["glyph_set"] = fields["map.glyph_set"]
    data["basins"]["enabled"] = [code for code in BASINS if fields[f"basin.{code}"]]
    for key, _label in NEARBY_FIELDS:
        data["nearby"][key] = number_or_text(str(fields[f"nearby.{key}"]))
    for key, _label in ALERT_FIELDS:
        data["alerts"][key] = bool(fields[f"alerts.{key}"])
    config, problems = parse_config(data)
    return config, problems


class SettingsScreen(ModalScreen[Config | None]):
    """Dismisses with the new config when saved, or None when cancelled."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save", priority=True),
    ]

    def __init__(self, config: Config, units: str) -> None:
        super().__init__()
        self.current = config
        self.units = units

    @property
    def eye(self) -> EyewallApp:
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        cfg = self.current
        with Vertical(id="settings-box"):
            with VerticalScroll(id="settings-scroll"):
                yield Static("Poll intervals (seconds)", classes="settings-head")
                for key in POLL_FIELDS:
                    yield self._row(key.capitalize(), Input(str(int(getattr(cfg.poll, key))), id=f"poll-{key}"))
                yield Static("Display", classes="settings-head")
                yield self._row(
                    "Units",
                    Select([(name, name) for name in PRESETS], value=self.units, allow_blank=False, id="units-preset"),
                )
                yield self._row(
                    "Glyph set",
                    Select(
                        [(name, name) for name in GLYPH_SETS],
                        value=cfg.map.glyph_set,
                        allow_blank=False,
                        id="map-glyph-set",
                    ),
                )
                yield Static("Basins", classes="settings-head")
                for code in BASINS:
                    yield self._row(BASIN_NAMES[code], Switch(code in cfg.basins.enabled, id=f"basin-{code}"))
                yield Static("Stations near a storm", classes="settings-head")
                for key, label in NEARBY_FIELDS:
                    yield self._row(label, Input(f"{getattr(cfg.nearby, key):g}", id=f"nearby-{key}"))
                yield Static("Alert rules", classes="settings-head")
                for key, label in ALERT_FIELDS:
                    yield self._row(label, Switch(bool(getattr(cfg.alerts, key)), id=f"alerts-{key}"))
            yield Static("", id="settings-note")

    @staticmethod
    def _row(label: str, widget: Input | Select[str] | Switch) -> Horizontal:
        return Horizontal(Static(label, classes="settings-label"), widget, classes="settings-row")

    def on_mount(self) -> None:
        box = self.query_one("#settings-box")
        box.border_title = "Settings"
        box.border_subtitle = "ctrl+s saves, esc cancels"

    def values(self) -> dict[str, Any]:
        def text(widget_id: str) -> str:
            return self.query_one(f"#{widget_id}", Input).value

        def choice(widget_id: str) -> str:
            value = self.query_one(f"#{widget_id}", Select).value
            return str(value)

        def flag(widget_id: str) -> bool:
            return self.query_one(f"#{widget_id}", Switch).value

        found: dict[str, Any] = {f"poll.{key}": text(f"poll-{key}") for key in POLL_FIELDS}
        found["units.preset"] = choice("units-preset")
        found["map.glyph_set"] = choice("map-glyph-set")
        found.update({f"basin.{code}": flag(f"basin-{code}") for code in BASINS})
        found.update({f"nearby.{key}": text(f"nearby-{key}") for key, _ in NEARBY_FIELDS})
        found.update({f"alerts.{key}": flag(f"alerts-{key}") for key, _ in ALERT_FIELDS})
        return found

    def action_save(self) -> None:
        config, problems = build_config(self.current, self.values())
        note = self.query_one("#settings-note", Static)
        if problems:
            note.update(Text("Not saved: " + "; ".join(problems[:3]), style="bold #ff4d4d"))
            return
        self.dismiss(config)

    def action_cancel(self) -> None:
        self.dismiss(None)
