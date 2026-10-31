import subprocess
import sys

import pytest

from eyewall import __version__
from eyewall.cli import build_parser, main, resolve_config


def parse(*argv: str):
    return build_parser().parse_args(list(argv))


def test_version_flag_prints_and_exits_zero(capsys):
    with pytest.raises(SystemExit) as raised:
        main(["--version"])
    assert raised.value.code == 0
    assert capsys.readouterr().out.strip() == f"eyewall {__version__}"


def test_module_entry_point_prints_the_version():
    result = subprocess.run([sys.executable, "-m", "eyewall", "--version"], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert result.stdout.strip() == f"eyewall {__version__}"


def test_config_and_no_config_are_mutually_exclusive():
    with pytest.raises(SystemExit) as raised:
        parse("--config", "a.toml", "--no-config")
    assert raised.value.code == 2


def test_replay_and_demo_are_mutually_exclusive():
    with pytest.raises(SystemExit) as raised:
        parse("--replay", "bundle", "--demo")
    assert raised.value.code == 2


def test_basin_is_case_insensitive_repeatable_and_validated():
    assert parse("--basin", "al", "--basin", "EP").basin == ["AL", "EP"]
    with pytest.raises(SystemExit):
        parse("--basin", "WP")


def test_flags_override_the_config_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[basins]\nenabled = ["AL", "EP", "CP"]\n[map]\nglyph_set = "unicode"\n', encoding="utf-8")
    config, warnings = resolve_config(parse("--config", str(path), "--basin", "cp", "--glyphs", "ascii"))
    assert warnings == ()
    assert config.basins.enabled == ("CP",)
    assert config.map.glyph_set == "ascii"


def test_no_config_ignores_the_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[poll]\nstorms = 99\n", encoding="utf-8")
    config, _ = resolve_config(parse("--no-config"))
    assert config.poll.storms == 300


def test_config_warnings_reach_stderr_and_the_app_starts(tmp_path, capsys, monkeypatch):
    launched = []
    monkeypatch.setattr("eyewall.app.run_app", lambda config, source, **kw: launched.append((config, source, kw)))
    path = tmp_path / "config.toml"
    path.write_text('[units]\npreset = "cubits"\n', encoding="utf-8")
    assert main(["--config", str(path)]) == 0
    assert "config: units.preset" in capsys.readouterr().err
    assert len(launched) == 1
    assert launched[0][2]["closer"] is not None  # the live source is closed on exit


def test_replay_starts_the_app_without_a_state_dir(monkeypatch):
    launched = []
    monkeypatch.setattr("eyewall.app.run_app", lambda config, source, **kw: launched.append((source, kw)))
    assert main(["--no-config", "--demo"]) == 0
    source, kw = launched[0]
    assert kw["state_dir"] is None
    assert type(source).__name__ == "ReplaySource"


def test_a_bad_replay_path_exits_two(capsys):
    assert main(["--no-config", "--replay", "no-such-bundle-anywhere"]) == 2
    assert capsys.readouterr().err.startswith("eyewall:")


def test_the_config_file_path_is_handed_to_the_app_so_settings_can_be_saved(tmp_path, monkeypatch):
    launched = []
    monkeypatch.setattr("eyewall.app.run_app", lambda config, source, **kw: launched.append(kw))
    path = tmp_path / "config.toml"
    assert main(["--config", str(path), "--demo"]) == 0
    assert launched[0]["config_path"] == path
    assert main(["--no-config", "--demo"]) == 0
    assert launched[1]["config_path"] is None
