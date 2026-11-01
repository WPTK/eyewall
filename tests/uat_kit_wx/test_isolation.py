"""The isolation helpers, tested with a planted write (no terminal, no exe: runs in the default suite everywhere)."""

from __future__ import annotations

from pathlib import Path

import pytest

from .isolation import ISOLATED, RealFolders, assert_isolated, isolated_env


def test_env_points_every_variable_into_the_root(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    assert set(env) == set(ISOLATED)
    assert_isolated(env, tmp_path)
    assert all(Path(v).is_dir() for v in env.values())  # the PyInstaller bootloader needs TEMP to exist


def test_assert_isolated_rejects_a_variable_outside_the_root(tmp_path: Path) -> None:
    env = isolated_env(tmp_path / "run")
    env["LOCALAPPDATA"] = str(tmp_path / "elsewhere")
    with pytest.raises(AssertionError, match="LOCALAPPDATA"):
        assert_isolated(env, tmp_path / "run")
    del env["APPDATA"]
    with pytest.raises(AssertionError, match="APPDATA"):
        assert_isolated(env, tmp_path / "run")


def test_real_folder_guard_sees_a_planted_write(tmp_path: Path) -> None:
    real = tmp_path / "eyewall"
    real.mkdir()
    (real / "cache.json").write_text("{}")
    other = tmp_path / "never-created"
    guard = RealFolders([real, other])
    assert guard.check() == []  # untouched: nothing reported
    (real / "cache.json").write_text('{"a": 1}')  # a changed file
    assert any(d.startswith("changed:") and d.endswith("cache.json") for d in guard.check())
    guard = RealFolders([real, other])
    (real / "new.txt").write_text("x")  # an added file
    assert [d for d in guard.check() if d.startswith("added:")]
    guard = RealFolders([real, other])
    (real / "new.txt").unlink()
    (real / "cache.json").unlink()  # a removed file
    assert [d for d in guard.check() if d.startswith("removed:")]
    guard = RealFolders([other])
    other.mkdir()  # the folder itself appears where there was none
    assert guard.check() == [f"added: {other}"]
