"""The README's install blocks must name things that exist, so a paste does what the page says."""

import re
from pathlib import Path

from eyewall.cli import build_parser

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
INSTALL_DOC = (ROOT / "docs" / "install.md").read_text(encoding="utf-8")
INSTALL = README.split("## Install", 1)[1].split("\n## ", 1)[0]


def built_assets() -> list[str]:
    """The release files binaries.yml builds: the one list the docs must match."""
    workflow = (ROOT / ".github" / "workflows" / "binaries.yml").read_text(encoding="utf-8")
    return re.findall(r"^\s+asset: (\S+)$", workflow, re.MULTILINE)


def test_install_doc_lists_every_built_asset() -> None:
    assets = built_assets()
    assert len(assets) == 5
    for asset in assets:
        assert f"`{asset}`" in INSTALL_DOC, asset
        assert asset in INSTALL, asset


def test_install_names_every_python_route() -> None:
    for route in ("uv tool install git+", "pipx install git+", "python -m pip install git+"):
        assert route in INSTALL
        assert route in INSTALL_DOC


def test_install_states_supported_systems() -> None:
    for text in (INSTALL, INSTALL_DOC):
        assert "Windows 11" in text
        assert "glibc 2.31" in text
        assert "musl" in text and "not supported" in text
        assert "git" in text


def test_demo_pictures_sentence() -> None:
    assert "In `--demo` the Pictures screen (`g`) is empty." in README


def test_every_flag_in_readme_commands_exists() -> None:
    known = {opt for action in build_parser()._actions for opt in action.option_strings}
    used: set[str] = set()
    for line in README.splitlines():
        if line.lstrip().startswith("eyewall"):
            used |= set(re.findall(r"(?<![\w-])(--[a-z][a-z-]+)", line))
    assert used and used <= known, used - known
