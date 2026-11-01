"""Per-click checks: click the real region of every clickable and require an observable change.

Chrome cells (footer, crumbs, health slot) are clicked at the cell range their `Target` declares; side-panel and page
links at their line; tabs, rows and widgets at the widget; map marks through the hit map. Marks also have to STICK: the
click opens a page, and after coming back and one refresh tick the mark must still be the marked one.
"""

from __future__ import annotations

from typing import Any

from textual import events
from textual.containers import VerticalScroll
from textual.widgets import DataTable, OptionList, SelectionList, Tab, Tabs

from eyewall.ui.chrome import ChromeScreen, FooterBar, TopBar
from eyewall.ui.screens.station import FollowLine
from eyewall.ui.widgets.map_view import MapView
from eyewall.ui.widgets.side_panel import SidePanel
from tests.uat.inventory import helpers
from tests.uat.inventory.checks_keys import DEMO, QUIET, install_exit_hook, snap
from tests.uat.inventory.inventory import SCREEN_OF, interactive_widgets, normalise, observe, widget_keys
from tests.uat.inventory.registry import RESULTS, World, check
from tests.uat.inventory.worlds import W

CLICK_SCREENS = (
    "main",
    "storm",
    "text",
    "buoys_near",
    "buoys_yours",
    "station_buoy",
    "station_gauge",
    "alerts",
    "graphics",
    "help",
    "feeds",
    "settings",
    "layers",
)


def on_screen(w: W, name: str, screen: Any) -> bool:
    depth = 1 if name in ("main", "full_map") else 2
    return type(w.screen) is type(screen) and len(w.app.screen_stack) == depth


async def click_cells(w: W, name: str, rec: Any) -> None:
    """Footer cells, crumbs and the health slot of the screen showing now."""
    shown = SCREEN_OF.get(name, name)
    screen = w.screen
    idempotent = {"key:c", "key:f", "key:enter"} if name == "full_map" else set()  # repeating or empty: no change by design
    if not isinstance(screen, ChromeScreen):
        return
    jobs: list[tuple[str, Any, Any]] = []
    for kind in (FooterBar, TopBar):
        for bar in screen.query(kind):
            for target in bar.row.targets if bar.row else ():
                a = target.action
                if kind is FooterBar:
                    item = f"click:footer:{shown}:{a}"
                elif a.startswith("app:crumb"):
                    item = f"click:crumb:{shown}:{a}"
                elif a == "app:feeds":
                    item = f"click:slot:{shown}"
                else:
                    item = f"click:topbar:{shown}:{a}"
                jobs.append((item, kind, target))
    crumbs = [t.action for _, k, t in jobs if k is TopBar and t.action.startswith("app:crumb")]
    for item, kind, target in jobs:
        if not on_screen(w, name, screen):
            await w.goto(name)
        bar = next(iter(w.screen.query(kind)))
        before = snap(w)
        try:
            await w.click(bar, (target.start, 0))
            after = snap(w)
        except Exception as exc:
            rec(item, f"{type(exc).__name__}: {exc}")
            continue
        last_crumb = bool(crumbs) and target.action == crumbs[-1]
        if before == after and not last_crumb and target.action not in idempotent:
            rec(item, f"clicking {target.action!r} ({kind.__name__} cells {target.start}-{target.end}) on {name} changed nothing")
        else:
            rec(item)


async def click_links(w: W, name: str, rec: Any) -> None:
    shown = SCREEN_OF.get(name, name)
    screen = w.screen
    done: set[str] = set()
    from eyewall.ui.widgets.page import Page

    for kind in (SidePanel, Page):
        for panel in list(screen.query(kind)):
            lines = panel._state.lines if kind is SidePanel else panel._lines
            for index, line in enumerate(lines):
                if not line.action:
                    continue
                item = f"click:link:{shown}:{panel.id}:{normalise(line.action)}"
                if item in done:
                    continue
                done.add(item)
                if not on_screen(w, name, screen):
                    await w.goto(name)
                    panel = w.screen.query_one(f"#{panel.id}")
                before = snap(w)
                try:
                    if isinstance(panel.parent, VerticalScroll):
                        panel.parent.scroll_to(y=max(0, index - 3), animate=False)
                        await w.settle()
                    await w.click(panel, (2, index + panel.styles.gutter.top))
                    await w.pilot.pause(0.1)
                    await w.settle()
                except Exception as exc:
                    rec(item, f"{type(exc).__name__}: {exc}")
                    continue
                if before == snap(w):
                    rec(item, f"clicking the {line.action!r} line ({index}) of #{panel.id} on {name} changed nothing")
                else:
                    rec(item)
    for follow in list(screen.query(FollowLine)):
        item = f"click:widget:{shown}:FollowLine:{follow.id}"
        before = snap(w)
        await w.click(follow)
        rec(item, None if before != snap(w) else "clicking the follow line changed nothing")


def widget_plan(w: W) -> list[tuple[type, str | None, int]]:
    """(class, id, index) of every interactive widget on the screen now: how to find it again after a screen change."""
    seen: dict[tuple[type, str | None], int] = {}
    plan = []
    for widget in interactive_widgets(w.screen):
        k = (type(widget), widget.id)
        plan.append((type(widget), widget.id, seen.get(k, 0)))
        seen[k] = seen.get(k, 0) + 1
    return plan


def find_widget(w: W, cls: type, wid: str | None, index: int) -> Any:
    found = [x for x in interactive_widgets(w.screen) if type(x) is cls and x.id == wid]
    return found[index] if index < len(found) else None


async def back_to(w: W, name: str, screen: Any) -> None:
    if not on_screen(w, name, screen):
        await w.goto(name)


async def click_widgets(w: W, name: str, rec: Any) -> None:
    shown = SCREEN_OF.get(name, name)
    screen = w.screen
    for cls, wid, index in widget_plan(w):
        await back_to(w, name, screen)
        widget = find_widget(w, cls, wid, index)
        if widget is None:
            continue
        kind = cls.__name__
        if isinstance(widget, Tabs):
            for tab in list(widget.query(Tab)):
                item = f"click:tab:{shown}:{tab.id}"
                await w.click(tab)
                rec(item, None if widget.active == tab.id else f"clicking tab {tab.id!r} left {widget.active!r} active on {name}")
        elif isinstance(widget, OptionList | DataTable | SelectionList):
            item = f"click:row:{shown}:{kind}"
            before = snap(w)
            try:
                await w.click(widget, (3, 1 if isinstance(widget, DataTable) else 0))
            except Exception as exc:
                rec(item, f"{type(exc).__name__}: {exc}")
                continue
            rec(item, None if before != snap(w) or widget.has_focus else f"clicking the first row of the {kind} on {name} changed nothing and took no focus")
        else:
            item = f"click:widget:{shown}:{kind}:{wid}"
            before = snap(w)
            widget.scroll_visible(animate=False)
            await w.settle()
            await w.click(widget)
            rec(item, None if before != snap(w) or widget.has_focus else f"clicking the {kind} #{wid} on {name} changed nothing and took no focus")


async def widget_key_checks(w: W, name: str, rec: Any) -> None:
    """The keys a list, tab bar or table answers to (up, down, enter, left, right, space) with the widget focused."""
    shown = SCREEN_OF.get(name, name)
    screen = w.screen
    for cls, wid, index in widget_plan(w):
        await back_to(w, name, screen)
        widget = find_widget(w, cls, wid, index)
        if widget is None:
            continue
        kind = cls.__name__
        size = getattr(widget, "option_count", None) or getattr(widget, "row_count", None) or len(list(widget.query(Tab)))
        for key in sorted(widget_keys(widget)):
            item = f"key:{shown}:{kind}:{key}"
            if (
                (kind == "DataTable" and key in ("left", "right", "enter"))
                or (kind == "OptionList" and name == "graphics" and key == "enter")
                or (kind == "Input" and key == "enter")
                or (size is not None and size < 2 and key in ("up", "down", "left", "right"))
                or (kind in ("StationList", "OptionList", "SelectionList") and key in ("left", "right"))
            ):
                rec(item)  # no-op by construction: one row, a whole-row cursor, a submit with nothing new, no sideways move
                continue
            await back_to(w, name, screen)
            widget = find_widget(w, cls, wid, index)
            if widget is None:
                continue
            widget.focus()
            await w.settle()
            before = snap(w)
            await w.press(key)
            rec(item, None if before != snap(w) else f"{key} on the focused {kind} of {name} changed nothing")


async def run_world_clicks(w: W, rec: Any, screens: tuple[str, ...] = CLICK_SCREENS) -> None:
    install_exit_hook(w)
    for name in screens:
        try:
            await w.goto(name)
            observe(w, name)
            await click_cells(w, name, rec)
            await w.goto(name)
            await click_links(w, name, rec)
            await w.goto(name)
            await click_widgets(w, name, rec)
            await w.goto(name)
            await widget_key_checks(w, name, rec)
        except Exception as exc:
            rec(f"click:crash:{name}", f"{type(exc).__name__}: {exc}")


@check(DEMO)
async def clicks_demo(w: W, rec: Any) -> None:
    await helpers.add_second_storm(w)  # so the storm-to-storm keys and links are on screen
    await run_world_clicks(w, rec)


@check(World("demo", (80, 24)))
async def clicks_small(w: W, rec: Any) -> None:
    """The small terminal draws the strip under the map and the full-screen map's own chrome."""
    await helpers.add_second_storm(w)
    await run_world_clicks(w, rec, ("main", "full_map"))


@check(QUIET)
async def clicks_quiet(w: W, rec: Any) -> None:
    await run_world_clicks(w, rec, ("main", "buoys_yours", "alerts"))


# ---- the map ----------------------------------------------------------------------------------------------------


@check(DEMO)
async def map_marks(w: W, rec: Any) -> None:
    for kind in ("storm", "buoy", "gauge"):
        item = f"click:mark:{kind}"
        try:
            main = await w.goto("main")
            view = main.query_one(MapView)
            try:
                mark, cell = helpers.lone_mark(view, kind)
            except AssertionError as exc:
                rec(item, f"no {kind} mark can be clicked on the demo map at 120x30: {exc}")
                continue
            await w.click(view, cell)
            opened = helpers.top_name(w)
            want = "StormScreen" if kind == "storm" else "StationScreen"
            if opened != want:
                rec(item, f"clicking the {kind} mark {mark.id} opened {opened}, not {want}")
                continue
            await w.press("escape")
            await w.after_tick()
            await w.pilot.pause(0.6)
            await w.after_tick()
            if helpers.map_of(w).focused_mark != mark:
                rec(item, f"after the click, the page and a refresh tick the {kind} mark {mark.id} is no longer the marked one")
            else:
                rec(item)
        except Exception as exc:
            rec(item, f"{type(exc).__name__}: {exc}")
    try:
        main = await w.goto("main")
        view = main.query_one(MapView)
        try:
            cell = helpers.crowded_cell(view)
        except AssertionError as exc:
            rec("click:mark:chooser", f"no overlapping marks at 120x30: {exc}")
        else:
            await w.click(view, cell)
            if helpers.top_name(w) != "MarkChooser":
                rec("click:mark:chooser", f"clicking overlapping marks opened {helpers.top_name(w)}")
            else:
                await w.press("escape")
                rec("key:chooser:escape", None if helpers.top_name(w) != "MarkChooser" else "escape left the chooser open")
                await w.click(view, cell)
                await w.press("enter")
                rec("click:mark:chooser", None if helpers.top_name(w) != "MarkChooser" else "enter in the chooser left it open")
    except Exception as exc:
        rec("click:mark:chooser", f"{type(exc).__name__}: {exc}")
    try:
        main = await w.goto("main")
        view = main.query_one(MapView)
        c = helpers.empty_cell(view)
        before = view.cursor
        await w.click(view, c)
        rec("click:mark:empty", None if view.cursor != before else "clicking empty sea did not move the cursor")
        before = view.viewport
        await w.pilot.mouse_down(view, offset=(20, 8))
        await w.pilot.hover(view, offset=(26, 10))
        await w.pilot.mouse_up(view, offset=(26, 10))
        await w.settle()
        rec("click:mark:drag", None if view.viewport != before else "dragging the map did not pan it")
        before = view.viewport
        view.post_message(events.MouseScrollUp(view, 20, 8, 20, 8, 0, 0, 0, False, False, False))
        await w.settle()
        rec("click:mark:wheel", None if view.viewport != before else "the wheel did not zoom the map")
        mark, cell = view.hits.drawn[0]
        await w.pilot.hover(view, offset=cell)
        await w.settle()
        rec("click:mark:hover", None if view.tooltip else "hovering a storm mark showed no tooltip")
    except Exception as exc:
        for g in ("empty", "drag", "wheel", "hover"):
            if f"click:mark:{g}" not in RESULTS:
                rec(f"click:mark:{g}", f"{type(exc).__name__}: {exc}")
