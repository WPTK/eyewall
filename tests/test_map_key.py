"""The map key names only the ring and line patterns the scene actually draws, in the palette's own words."""

from __future__ import annotations

import pytest

from eyewall.palette import SPARSE, WATCH_WARNING_CUES, WatchWarning
from eyewall.render.canvas import Mode
from eyewall.render.layers import MapOptions, MapScene, StormScene, WarningSegment, WindRadii
from eyewall.ui.widgets.map_view import MapView
from tests.ui_support import into_the_storm, replay_app, running, screen_text

LINE = ((30.0, -80.0), (30.0, -75.0))
FULL = (100.0, 80.0, 60.0, 90.0)


def key(scene: MapScene, *, mode: Mode = Mode.BRAILLE, options: MapOptions | None = None) -> str:
    view = MapView(mode=mode, options=options)
    view.scene = scene
    return " ".join(item for item in (part for part in view.legend(200).plain.split("\n")[1:]))


def warned(*kinds: WatchWarning) -> MapScene:
    segments = tuple(WarningSegment(kind, LINE) for kind in kinds)
    return MapScene(storms=(StormScene(warnings=segments),))


def test_no_key_when_nothing_with_a_pattern_is_drawn() -> None:
    assert key(MapScene(storms=(StormScene(),))) == ""
    assert key(MapScene(storms=(StormScene(radii=(WindRadii(25.0, -70.0),)),))) == ""  # radii with no quadrants


def test_a_ring_is_listed_only_when_it_has_quadrants() -> None:
    radii = WindRadii(25.0, -70.0, kt34=FULL, kt50=(0.0, 0.0, 0.0, 0.0), kt64=None)
    text = key(MapScene(storms=(StormScene(radii=(radii,)),)))
    assert "34kt" in text and "50kt" not in text and "64kt" not in text


def test_only_a_tropical_storm_warning_is_listed() -> None:
    text = key(warned(WatchWarning.TROPICAL_STORM_WARNING))
    assert WATCH_WARNING_CUES[WatchWarning.TROPICAL_STORM_WARNING].short in text
    assert "watch" not in text.lower() and "surge" not in text.lower()


def test_a_hurricane_watch_is_listed_by_its_own_name_not_a_generic_one() -> None:
    text = key(warned(WatchWarning.HURRICANE_WATCH))
    assert WATCH_WARNING_CUES[WatchWarning.HURRICANE_WATCH].short in text
    assert WATCH_WARNING_CUES[WatchWarning.TROPICAL_STORM_WATCH].short not in text


def test_surge_lines_come_from_the_surge_field_and_both_kinds_are_named() -> None:
    surge = (WarningSegment(WatchWarning.SURGE_WATCH, LINE), WarningSegment(WatchWarning.SURGE_WARNING, LINE))
    text = key(MapScene(storms=(StormScene(surge=surge),)))
    assert all(WATCH_WARNING_CUES[k].short in text for k in (WatchWarning.SURGE_WATCH, WatchWarning.SURGE_WARNING))


def test_the_key_follows_the_layer_switches_and_the_ascii_set() -> None:
    scene = warned(WatchWarning.HURRICANE_WARNING)
    assert key(scene, options=MapOptions(warnings=False)) == ""
    assert "---" in key(scene, mode=Mode.ASCII)


def test_surge_watch_and_warning_have_different_patterns() -> None:
    watch, warning = (WATCH_WARNING_CUES[k].pattern for k in (WatchWarning.SURGE_WATCH, WatchWarning.SURGE_WARNING))
    assert watch != warning and watch == SPARSE


@pytest.mark.parametrize("size", [(120, 30), (200, 50)], ids=lambda s: f"{s[0]}x{s[1]}")
async def test_the_pane_reserves_every_key_row_when_rings_and_lines_are_drawn(size) -> None:  # type: ignore[no-untyped-def]
    app = replay_app()
    async with running(app, size) as pilot:
        await into_the_storm(pilot)
        view = app.screen.map_view
        radii = WindRadii(25.0, -70.0, kt34=FULL, kt50=FULL, kt64=FULL)
        kinds = tuple(WatchWarning)
        scene = MapScene(
            storms=(
                StormScene(
                    radii=(radii,),
                    warnings=tuple(WarningSegment(k, LINE) for k in kinds[:4]),
                    surge=tuple(WarningSegment(k, LINE) for k in kinds[4:]),
                ),
            )
        )
        view.set_scene(scene)
        await pilot.pause()
        pane, legend = app.screen.query_one("#map-pane"), app.screen.query_one(".legend")
        rows = view.legend(pane.size.width).plain.count("\n") + 1
        assert rows >= 2 and legend.size.height == rows
        assert legend.region.bottom == pane.region.bottom
        shown = " ".join(screen_text(app).splitlines()[legend.region.y : legend.region.bottom])
        assert "lines" in shown  # the key keeps whole items from the left: the lines first, the rings when there is room
        assert ("rings" in shown and "34kt" in shown) == (pane.size.width >= 150)
