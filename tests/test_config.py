import tomllib
from dataclasses import replace

from eyewall.config import (
    POLL_LIMITS,
    Config,
    NearbyConfig,
    PollConfig,
    WatchlistConfig,
    apply_overrides,
    default_path,
    load_config,
    parse_config,
    save_config,
    to_dict,
)


def parse(text: str) -> tuple[Config, list[str]]:
    return parse_config(tomllib.loads(text))


def test_empty_file_is_the_defaults_with_no_warnings():
    config, warnings = parse("")
    assert config == Config()
    assert warnings == []


def test_defaults_match_the_documented_values():
    config = Config()
    assert config.poll.storms == 300
    assert config.poll.buoys == 600
    assert config.basins.enabled == ("AL", "EP", "CP")
    assert config.nearby == NearbyConfig(300, 150, 72, 40)
    assert config.units.preset == "nautical"
    assert config.map.glyph_set == "unicode"
    assert config.graphics.inline == "auto"
    assert config.alerts.bell is False


def test_values_are_read():
    config, warnings = parse(
        """
        [poll]
        storms = 900
        [basins]
        enabled = ["ep", "AL"]
        [nearby]
        radius_now_nm = 500
        max_stations = 10
        [units]
        preset = "METRIC"
        [watchlist]
        ndbc = ["41047", "kyfc1"]
        coops = [8721604]
        [map]
        glyph_set = "ascii"
        cone = false
        [alerts]
        bell = true
        [graphics]
        inline = "never"
        """
    )
    assert warnings == []
    assert config.poll.storms == 900
    assert config.basins.enabled == ("AL", "EP")  # canonical order
    assert config.nearby.radius_now_nm == 500
    assert config.nearby.max_stations == 10
    assert config.units.preset == "metric"
    assert config.watchlist == WatchlistConfig(ndbc=("41047", "KYFC1"), coops=("8721604",))
    assert config.map.glyph_set == "ascii"
    assert config.map.cone is False
    assert config.alerts.bell is True
    assert config.graphics.inline == "never"


def test_bad_values_fall_back_with_a_warning_each():
    config, warnings = parse(
        """
        [poll]
        storms = "fast"
        buoys = 5
        tides = true
        [nearby]
        track_hours = 3.5
        max_stations = 0
        [units]
        preset = "cubits"
        [map]
        land = "yes"
        glyph_set = "emoji"
        """
    )
    assert config == Config()
    assert len(warnings) == 8
    assert any("poll.storms" in w for w in warnings)
    assert any("poll.buoys" in w and "outside" in w for w in warnings)
    assert any("units.preset" in w for w in warnings)


def test_unknown_keys_and_sections_are_ignored_quietly():
    config, warnings = parse("[poll]\nfuture_feed = 1\n[hologram]\nenabled = true\n")
    assert config == Config()
    assert warnings == []


def test_a_section_that_is_not_a_table_is_ignored():
    config, warnings = parse('poll = 3\nunits = "metric"\n')
    assert config == Config()
    assert len(warnings) == 2


def test_basins_are_filtered_and_never_empty():
    config, warnings = parse('[basins]\nenabled = ["WP", "ep", "EP"]\n')
    assert config.basins.enabled == ("EP",)
    assert len(warnings) == 1
    config, warnings = parse('[basins]\nenabled = ["WP"]\n')
    assert config.basins.enabled == ("AL", "EP", "CP")
    assert len(warnings) == 2
    config, warnings = parse('[basins]\nenabled = "AL"\n')
    assert config.basins.enabled == ("AL", "EP", "CP")


def test_watchlist_ids_are_normalised_deduplicated_and_validated():
    config, warnings = parse('[watchlist]\nndbc = ["41010", "41010", " 42001 ", "", "no way", true]\n')
    assert config.watchlist.ndbc == ("41010", "42001")
    assert len(warnings) == 3
    config, warnings = parse('[watchlist]\nndbc = []\ncoops = "8721604"\n')
    assert config.watchlist.ndbc == ()
    assert config.watchlist.coops == WatchlistConfig().coops
    assert len(warnings) == 1


def test_watchlist_is_capped():
    ids = ", ".join(f'"{40000 + n}"' for n in range(70))
    config, warnings = parse(f"[watchlist]\nndbc = [{ids}]\n")
    assert len(config.watchlist.ndbc) == 60
    assert len(warnings) == 1


def test_missing_default_file_is_quietly_the_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr("eyewall.config.default_path", lambda: tmp_path / "nope" / "config.toml")
    result = load_config()
    assert result.config == Config()
    assert result.warnings == ()


def test_missing_explicit_file_warns(tmp_path):
    result = load_config(tmp_path / "nope.toml")
    assert result.config == Config()
    assert len(result.warnings) == 1


def test_invalid_toml_falls_back_with_a_warning(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[poll\nstorms = ", encoding="utf-8")
    result = load_config(path)
    assert result.config == Config()
    assert len(result.warnings) == 1
    assert "could not read" in result.warnings[0]


def test_use_file_false_skips_the_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[poll]\nstorms = 900\n", encoding="utf-8")
    assert load_config(path, use_file=False).config == Config()
    assert load_config(path).config.poll.storms == 900


def test_save_then_load_round_trips(tmp_path):
    config = replace(
        Config(),
        poll=replace(PollConfig(), storms=900.0),
        watchlist=WatchlistConfig(ndbc=("41010",), coops=()),
    )
    path = save_config(config, tmp_path / "deep" / "config.toml")
    result = load_config(path)
    assert result.warnings == ()
    assert result.config == config
    assert not list(path.parent.glob(".config-*"))


def test_to_dict_is_plain_toml_data():
    data = to_dict(Config())
    assert data["basins"]["enabled"] == ["AL", "EP", "CP"]
    assert isinstance(data["watchlist"]["ndbc"], list)


def test_overrides_win_and_are_validated():
    config = apply_overrides(Config(), basins=["ep", "AL"], glyph_set="ascii")
    assert config.basins.enabled == ("AL", "EP")
    assert config.map.glyph_set == "ascii"
    assert apply_overrides(Config(), basins=[], glyph_set=None) == Config()
    assert apply_overrides(Config(), basins=["WP"], glyph_set="emoji") == Config()


def test_default_path_is_under_an_eyewall_directory():
    assert default_path().name == "config.toml"
    assert default_path().parent.name.lower() == "eyewall"


def test_no_interval_can_be_set_below_the_documented_cadence():
    defaults = PollConfig()
    for feed in ("storms", "outlook", "alerts", "buoys", "tides", "satellite"):
        low, _high = POLL_LIMITS[feed]
        assert low == getattr(defaults, feed), feed  # the default is the documented cadence and the floor
        config, warnings = parse(f"[poll]\n{feed} = {low - 1}\n")
        assert getattr(config.poll, feed) == low
        assert any(f"poll.{feed}" in w and "outside" in w for w in warnings)
        config, warnings = parse(f"[poll]\n{feed} = {low}\n")
        assert getattr(config.poll, feed) == low
        assert warnings == []


def test_a_config_file_saved_with_a_byte_order_mark_still_loads(tmp_path):
    path = tmp_path / "config.toml"
    path.write_bytes("﻿[poll]\nstorms = 600\n".encode())
    result = load_config(path)
    assert result.config.poll.storms == 600
    assert result.warnings == ()
