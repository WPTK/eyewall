"""The graphics screen: the storm's image gallery with the whole terminal to draw in."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Static

from eyewall.palette import ACCENT, DIM
from eyewall.ui import format as fmt
from eyewall.ui.chrome import ChromeScreen, FooterBar, TopBar
from eyewall.ui.widgets.gallery import GalleryPanel

if TYPE_CHECKING:
    pass


class GraphicsScreen(ChromeScreen):
    CRUMB = "Graphics"

    def __init__(self, storm_id: str) -> None:
        super().__init__()
        self.storm_id = storm_id

    def compose(self) -> ComposeResult:
        yield TopBar()
        yield Static("", id="graphics-title")
        yield GalleryPanel(self.storm_id, id="graphics-gallery")
        yield FooterBar()

    def on_mount(self) -> None:
        gallery = self.query_one(GalleryPanel)
        gallery.set_active(True)
        gallery.focus_list()
        self.refresh_data()

    def on_screen_suspend(self) -> None:
        self.query_one(GalleryPanel).set_active(False)

    def on_screen_resume(self) -> None:
        self.query_one(GalleryPanel).set_active(True)

    def refresh_data(self) -> None:
        state = self.eye.store.storms.get(self.storm_id)
        title = self.query_one("#graphics-title", Static)
        if state is None:
            title.update(
                Text(f" {self.storm_id.upper()} is no longer active. Press Esc to go back.", style=f"bold {ACCENT}")
            )
        else:
            storm = state.storm
            head = Text(no_wrap=True, overflow="ellipsis")
            head.append(f" {storm.name.title() or storm.id.upper()}", style=f"bold {fmt.storm_color(storm)}")
            head.append("  pictures", style=DIM)
            title.update(head)
        self.query_one(GalleryPanel).refresh_data()
