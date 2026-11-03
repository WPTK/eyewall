"""Focus follows visibility: a widget that is hidden cannot hold focus, so arrows and paging never go nowhere."""

from __future__ import annotations

from typing import Any

from textual.screen import Screen
from textual.widget import Widget


def show(screen: Screen[Any], widget: Widget, shown: bool) -> None:
    """Show or hide `widget` and keep focus on something visible.

    A hidden widget stops being focusable (and gives up focus if it had it); a shown one takes focus back when the
    screen has nothing focused. Textual's own auto-focus runs before the first layout and cannot know this.
    """
    widget.display = shown
    widget.can_focus = shown
    if shown:
        if screen.focused is None:
            widget.focus()
    elif screen.focused is widget:
        screen.set_focus(None)
