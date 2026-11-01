"""NHC's outlook in plain sentences, one per area with its exact chances, as a small dialog over the main screen.

A stand-in until the text products have their own screen (PR7); `O` on the main screen opens it, so the chances stay
reachable at 80x24 where the strip has room for a count only.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from eyewall.palette import HEADING


def outlook_body(sentences: list[str]) -> Text:
    out = Text()
    out.append("What NHC is watching\n\n", style=f"bold {HEADING}")
    out.append("\n\n".join(sentences) if sentences else "Nothing in the outlook right now.")
    out.append("\n\nEsc closes this.", style="dim")
    return out


class OutlookNote(ModalScreen[None]):
    BINDINGS = [Binding("escape,O", "close", "Close")]

    def __init__(self, sentences: list[str]) -> None:
        super().__init__()
        self.sentences = sentences

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="outlook-box"):
            yield Static(outlook_body(self.sentences), id="outlook-text")

    def action_close(self) -> None:
        self.dismiss()
