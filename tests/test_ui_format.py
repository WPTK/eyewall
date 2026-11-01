"""Pure helpers behind the interface: coordinate text and the map's fit points."""

from eyewall.ui.adapt import basin_points
from eyewall.ui.products import fmt_lat, fmt_lon


def test_coordinates_carry_hemisphere_letters():
    assert fmt_lat(25.1) == "25.1N"
    assert fmt_lat(-3.0) == "3.0S"
    assert fmt_lon(-75.25) in {"75.2W", "75.3W"}
    assert fmt_lon(170.0) == "170.0E"


def test_basin_points_fit_one_basin_or_all():
    assert len(basin_points(("AL",))) == 2
    assert len(basin_points(())) == len(basin_points(("AL", "EP", "CP")))


def test_storm_list_shows_a_header_only_for_a_basin_with_storms():
    from datetime import UTC, datetime

    from eyewall.state.store import Store
    from eyewall.ui.format import build_rows
    from eyewall.ui.glyphs import UNICODE
    from eyewall.units import PRESETS

    store = Store()
    store.storms_loaded = True
    rows = build_rows(store, ("AL", "EP", "CP"), datetime(2026, 1, 1, tzinfo=UTC), PRESETS["nautical"], UNICODE)
    assert [r.kind for r in rows] == ["quiet"]
    assert rows[0].text.plain.strip() == "No tropical cyclones"


def test_no_connection_needs_storms_never_loaded_and_the_storms_feed_failing():
    from datetime import UTC, datetime

    from eyewall.state.store import Store
    from eyewall.ui.format import build_rows
    from eyewall.ui.glyphs import UNICODE
    from eyewall.units import PRESETS

    now = datetime(2026, 1, 1, tzinfo=UTC)

    def line(*, loaded: bool, unreachable: bool) -> str:
        store = Store()
        store.storms_loaded = loaded
        rows = build_rows(store, ("AL",), now, PRESETS["nautical"], UNICODE, unreachable=unreachable)
        return rows[0].text.plain.strip()

    assert line(loaded=False, unreachable=True) == "no connection"
    assert line(loaded=False, unreachable=False) == "loading..."
    assert (
        line(loaded=True, unreachable=True) == "No tropical cyclones"
    )  # storms answered once; the outage is elsewhere
