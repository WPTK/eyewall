"""Spike S4 test target: button+counter, clickable list, key 2-5 change a label.

Events are appended to $S4_LOG as JSON lines.
"""

import json
import os
import time

from textual.app import App, ComposeResult
from textual.widgets import Button, Label, ListItem, ListView

LOG = os.environ.get("S4_LOG", "/tmp/s4_app.jsonl")


def emit(kind: str, **kw: object) -> None:
    with open(LOG, "a") as f:
        f.write(json.dumps({"t": time.time(), "kind": kind, **kw}) + "\n")


class S4(App):
    CSS = "Screen{layout:vertical} #btn{width:24;margin:1 2} Label{margin:0 2} ListView{height:8;margin:1 2}"
    BINDINGS = [("q", "quit", "quit")]

    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def compose(self) -> ComposeResult:
        yield Label("label=ready", id="status")
        yield Button("Click me", id="btn")
        yield Label("count=0", id="counter")
        yield ListView(*[ListItem(Label(f"item-{c}")) for c in "ABCDE"], id="lst")
        yield Label("sel=none", id="sel")

    def on_mount(self) -> None:
        self.set_timer(0.8, self.report_ready)

    def report_ready(self) -> None:
        def reg(w):
            r = w.region
            return {"x": r.x, "y": r.y, "w": r.width, "h": r.height}

        emit(
            "ready",
            size=[self.size.width, self.size.height],
            btn=reg(self.query_one("#btn")),
            lst=reg(self.query_one("#lst")),
        )

    def on_key(self, event) -> None:
        emit("key", key=event.key, char=event.character)
        names = {"2": "TWO", "3": "THREE", "4": "FOUR", "5": "FIVE"}
        if event.key in names:
            self.query_one("#status", Label).update(f"label={names[event.key]}")

    def on_mouse_down(self, event) -> None:
        emit("mouse_down", x=event.screen_x, y=event.screen_y, button=event.button)

    def on_button_pressed(self, event) -> None:
        self.count += 1
        self.query_one("#counter", Label).update(f"count={self.count}")
        emit("button", count=self.count)

    def on_list_view_selected(self, event) -> None:
        t = str(event.item.query_one(Label).renderable)
        self.query_one("#sel", Label).update(f"sel={t}")
        emit("list_selected", item=t)


if __name__ == "__main__":
    S4().run()
