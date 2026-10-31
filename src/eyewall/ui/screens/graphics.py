"""The graphics screen: the storm's image gallery with the whole terminal to draw in."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import OptionList, Static

from eyewall.ui import format as fmt
from eyewall.ui.theme import DIM
from eyewall.ui.widgets.gallery import GalleryPanel

if TYPE_CHECKING:
    from eyewall.app import EyewallApp


class GraphicsScreen(Screen[None]):
    BINDINGS = [Binding("escape,backspace", "back", "Back")]

    def __init__(self, storm_id: str) -> None:
        super().__init__()
        self.storm_id = storm_id

    @property
    def eye(self) -> EyewallApp:
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        yield Static("", id="graphics-title")
        yield GalleryPanel(self.storm_id, id="graphics-gallery")
        yield Static("", id="graphics-status")

    def on_mount(self) -> None:
        gallery = self.query_one(GalleryPanel)
        gallery.set_active(True)
        gallery.query_one(OptionList).focus()
        self.refresh_data()
        self.refresh_status()

    def on_screen_suspend(self) -> None:
        self.query_one(GalleryPanel).set_active(False)

    def on_screen_resume(self) -> None:
        self.query_one(GalleryPanel).set_active(True)

    def refresh_data(self) -> None:
        state = self.eye.store.storms.get(self.storm_id)
        title = self.query_one("#graphics-title", Static)
        if state is None:
            title.update(
                Text(f" {self.storm_id.upper()} is no longer active. Press Esc to go back.", style="bold #ffa63d")
            )
        else:
            storm = state.storm
            head = Text(no_wrap=True, overflow="ellipsis")
            head.append(f" {fmt.class_label(storm)} ", style=f"bold {fmt.storm_color(storm)}")
            head.append(storm.name.upper(), style="bold")
            head.append("  graphics", style=DIM)
            title.update(head)
        self.query_one(GalleryPanel).refresh_data()

    def refresh_status(self) -> None:
        self.query_one("#graphics-status", Static).update(self.eye.status_text(self.size.width))

    def action_back(self) -> None:
        self.app.pop_screen()
