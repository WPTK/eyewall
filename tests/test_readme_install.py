"""The README and docs/install.md name things that exist, so a paste does what the page says."""

import re
from pathlib import Path

from eyewall.cli import build_parser

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
INSTALL_DOC = (ROOT / "docs" / "install.md").read_text(encoding="utf-8")
USAGE_DOC = (ROOT / "docs" / "usage.md").read_text(encoding="utf-8")
PREREQUISITES = README.split("## Prerequisites", 1)[1].split("\n## ", 1)[0]
QUICKSTART = README.split("## Quickstart", 1)[1].split("\n## ", 1)[0]


def built_assets() -> list[str]:
    """The release files binaries.yml builds: the one list the docs must match."""
    workflow = (ROOT / ".github" / "workflows" / "binaries.yml").read_text(encoding="utf-8")
    return re.findall(r"^\s+asset: (\S+)$", workflow, re.MULTILINE)


def test_install_doc_lists_every_built_asset() -> None:
    assets = built_assets()
    assert len(assets) == 5
    for asset in assets:
        assert f"`{asset}`" in INSTALL_DOC, asset


def test_install_names_every_python_route() -> None:
    for route in ("uv tool install git+", "pipx install git+", "python -m pip install git+"):
        assert route in QUICKSTART
        assert route in INSTALL_DOC


def test_install_states_supported_systems() -> None:
    for text in (PREREQUISITES, INSTALL_DOC):
        assert "Windows 11" in text
        assert "glibc 2.31" in text
        assert "musl" in text and "not supported" in text
        assert "git" in text
        assert "macOS 14" in text and "macOS 15" in text


def test_demo_pictures_are_documented_as_recorded_stills() -> None:
    """The bundled recording holds cone stills, so the docs must not call the demo's Pictures screen empty."""
    assert "is empty" not in README
    assert "cone stills" in USAGE_DOC


def test_every_flag_in_documented_commands_exists() -> None:
    known = {opt for action in build_parser()._actions for opt in action.option_strings}
    used: set[str] = set()
    for text in (README, INSTALL_DOC, USAGE_DOC):
        for line in text.splitlines():
            if line.lstrip().startswith("eyewall"):
                used |= set(re.findall(r"(?<![\w-])(--[a-z][a-z-]+)", line))
    assert used and used <= known, used - known
