"""The README's install blocks must name things that exist, so a paste does what the page says."""

import re
from pathlib import Path

from eyewall.cli import build_parser

README = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
INSTALL = README.split("## Install", 1)[1].split("\n## ", 1)[0]


def test_install_names_every_route() -> None:
    for route in ("uv tool install git+", "pipx install git+", "python -m pip install git+"):
        assert route in INSTALL
    for asset in ("eyewall-windows-x86_64.exe", "eyewall-linux-x86_64.tar.gz", "eyewall-macos-arm64.tar.gz"):
        assert asset in INSTALL


def test_install_states_supported_systems() -> None:
    assert "Windows 11" in INSTALL
    assert "glibc 2.31" in INSTALL
    assert "musl" in INSTALL


def test_every_flag_in_readme_exists() -> None:
    known = {opt for action in build_parser()._actions for opt in action.option_strings}
    used = set(re.findall(r"(?<![\w-])(--[a-z][a-z-]+)", README))
    assert used <= known, used - known
