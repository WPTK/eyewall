"""The layer menu: which map layers are drawn."""

from __future__ import annotations

from dataclasses import fields, replace

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import SelectionList

from eyewall.render.layers import MapOptions
from eyewall.ui.widgets.map_view import LAYER_NAMES


class LayerMenu(ModalScreen[MapOptions | None]):
    """A checklist of the layers. Space toggles, Enter applies, Esc leaves the layers as they were."""

    BINDINGS = [Binding("escape", "cancel", "Cancel"), Binding("enter", "apply", "Apply", priority=True)]

    def __init__(self, options: MapOptions) -> None:
        super().__init__()
        self.options = options

    def compose(self) -> ComposeResult:
        with Vertical(id="layer-box"):
            yield SelectionList[str](
                *[
                    (LAYER_NAMES.get(f.name, f.name), f.name, bool(getattr(self.options, f.name)))
                    for f in fields(self.options)
                ],
                id="layer-list",
            )

    def on_mount(self) -> None:
        box = self.query_one("#layer-box")
        box.border_title = "Map layers"
        box.border_subtitle = "space toggles, enter applies"

    def action_apply(self) -> None:
        chosen = set(self.query_one("#layer-list", SelectionList).selected)
        self.dismiss(replace(self.options, **{f.name: f.name in chosen for f in fields(self.options)}))

    def action_cancel(self) -> None:
        self.dismiss(None)
