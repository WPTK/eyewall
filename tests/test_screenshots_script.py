import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "screenshots", Path(__file__).resolve().parent.parent / "scripts" / "screenshots.py"
)
assert SPEC is not None and SPEC.loader is not None
screenshots = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(screenshots)


def test_greyscale_svg_has_no_chromatic_colours() -> None:
    assert screenshots.chromatic_colours('fill="#121212" fill="#e0e0e0" fill="#ffffff"') == set()


def test_colour_svg_lists_distinct_chromatic_colours() -> None:
    svg = 'fill="#121212" fill="#4aa3ff" fill="#4AA3FF" fill: #ffa63d;'
    assert screenshots.chromatic_colours(svg) == {"4aa3ff", "ffa63d"}
