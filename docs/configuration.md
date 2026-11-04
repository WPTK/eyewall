# Configuration

eyewall works with no configuration. This page lists every setting, its default and its limits.

## Where settings come from

eyewall applies settings in this order, and each step overrides the one before it:

1. The built-in defaults.
2. The config file.
3. Command-line flags. Flags are never written back to the file.

The config file is `config.toml` in your user config directory:

| System | Default path |
| --- | --- |
| Windows | `%LOCALAPPDATA%\eyewall\config.toml` |
| Linux | `~/.config/eyewall/config.toml` (`$XDG_CONFIG_HOME/eyewall` if set) |
| macOS | `~/Library/Application Support/eyewall/config.toml` |

`eyewall --diagnose` prints the exact path on your machine. The first save from the settings screen (`S`, then
`Ctrl+S`) creates the file. A save rewrites the whole file, so comments you added are lost. If the file exists but
cannot be read, eyewall keeps a `.bak` copy before it saves over it.

Loading never fails. A missing file means the defaults. A file that is not valid TOML means the defaults plus a
warning. A value of the wrong type or outside its limits is dropped with a warning, and the default stands. Unknown
keys are ignored, so a file written by a newer version still opens in an older one.

## Command-line flags

| Flag | Default | Description |
| --- | --- | --- |
| `--config PATH` | the user config file | Read this file instead. A missing file gives a warning and the defaults. |
| `--no-config` | off | Ignore the file. Changes you make in the app last for the run. |
| `--basin {AL,EP,CP}` | all enabled | Show only this basin. Repeat the flag for several. Overrides `[basins] enabled`. |
| `--glyphs {unicode,ascii}` | automatic | Symbol set for the map. Overrides `[map] glyph_set`. Without the flag, eyewall uses `ascii` when the terminal cannot draw braille and box characters, and your file's value otherwise. |
| `--state-dir DIR` | the user data directory | Where the set of seen alerts is saved. A replay keeps none unless you pass this flag. |

The data directory is `%LOCALAPPDATA%\eyewall` on Windows, `~/.local/share/eyewall` on Linux and
`~/Library/Application Support/eyewall` on macOS.

## Environment variables

| Variable | Default | Description |
| --- | --- | --- |
| `NO_COLOR` | unset | Any non-empty value turns color off. Words, glyphs and line patterns carry every meaning that color does. |
| `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY` | unset | Route requests to NOAA through a proxy. On Windows and macOS the system proxy setting applies too. |
| `TERM`, `COLORTERM`, `WT_SESSION`, `TERM_PROGRAM`, `LANG`, `LC_ALL`, `LC_CTYPE` | your shell's | eyewall reads these once at startup to choose the color depth and the symbol set. `eyewall --diagnose` shows what it decided. |
| `XDG_CONFIG_HOME` | `~/.config` | Linux only. Moves the config directory. |

## Config file keys

Sections and keys are shown in TOML. Every key is optional.

### `[poll]`

Seconds between polls of each feed. The default for each key is also its lowest allowed value, because the defaults
match the cadence NOAA publishes at. See `docs/data-sources.md`.

| Key | Default | Allowed | Description |
| --- | --- | --- | --- |
| `storms` | `300` | 300 to 3600 | Active storms, advisories and wind radii. |
| `outlook` | `1800` | 1800 to 86400 | Tropical weather outlook. |
| `alerts` | `300` | 300 to 3600 | NWS watches and warnings. |
| `buoys` | `600` | 600 to 3600 | NDBC buoy observations. |
| `tides` | `360` | 360 to 3600 | CO-OPS tide gauge readings. |
| `satellite` | `600` | 600 to 3600 | NESDIS satellite listing. |
| `backoff_max` | `1800` | 60 to 86400 | Longest wait after repeated failures. The delay doubles with each failure up to this value. |
| `away_after` | `300` | 30 to 86400 | Seconds without keyboard or mouse input before eyewall counts you as away and polls more slowly. |

The settings screen edits the first six keys. `backoff_max` and `away_after` are file-only.

### `[basins]`

| Key | Default | Allowed | Description |
| --- | --- | --- | --- |
| `enabled` | `["AL", "EP", "CP"]` | any of `"AL"`, `"EP"`, `"CP"` | Basins to watch: Atlantic, East Pacific, Central Pacific. A list with no valid basin gives all three. |

### `[nearby]`

A station counts as near a storm when it is within `radius_now_nm` of the storm's center now, or within
`radius_track_nm` of the forecast track. Stations on your watchlist always count.

| Key | Default | Allowed | Description |
| --- | --- | --- | --- |
| `radius_now_nm` | `300` | 10 to 2000 | Nautical miles from the storm's current center. |
| `radius_track_nm` | `150` | 10 to 1000 | Nautical miles from the forecast track. |
| `track_hours` | `72` | 6 to 120 (whole number) | How many hours of forecast track to check. |
| `max_stations` | `40` | 1 to 200 (whole number) | Most stations to list. The cap never removes a watchlist station. |

### `[units]`

| Key | Default | Allowed | Description |
| --- | --- | --- | --- |
| `preset` | `"nautical"` | `"nautical"`, `"us"`, `"metric"` | Wind in knots, mph or km/h; pressure in mb, inHg or hPa; distance in nm, mi or km. The `u` key cycles the presets. |

### `[watchlist]`

Stations that always show, with or without a storm. Follow a station with `f` on its page to add it. Ids are
upper-cased and duplicates are dropped. An id must be 3 to 10 letters or digits. Each list holds at most 60 ids.

| Key | Default | Description |
| --- | --- | --- |
| `ndbc` | `["41010", "42001", "41047"]` | NDBC buoy and C-MAN station ids. |
| `coops` | `["8721604"]` | CO-OPS tide gauge ids. |

### `[map]`

| Key | Default | Allowed | Description |
| --- | --- | --- | --- |
| `land` | `true` | `true`, `false` | Fill land. |
| `borders` | `true` | `true`, `false` | Draw country and state borders. |
| `cone` | `true` | `true`, `false` | Draw the forecast cone. |
| `radii` | `true` | `true`, `false` | Draw the 34, 50 and 64 knot wind radii. |
| `glyph_set` | `"unicode"` | `"unicode"`, `"ascii"` | Symbols for the map. The `ascii` set also turns off inline pictures. |

These keys set the starting layers. The Layers dialog (`l`) changes them for the current session only. The settings
screen edits `glyph_set` but not the other four.

### `[alerts]`

Each key switches one kind of alert on or off.

| Key | Default | Description |
| --- | --- | --- |
| `new_advisory` | `true` | A new advisory or discussion. |
| `classification` | `true` | A change of classification, and rapid intensification. |
| `watches_warnings` | `true` | A watch or warning issued, changed or discontinued. |
| `outlook` | `true` | A new outlook area or a new invest. |
| `buoy_thresholds` | `true` | A buoy passing a wind threshold, or going silent. |
| `bell` | `false` | Ring the terminal bell when new events arrive. |

### `[graphics]`

| Key | Default | Allowed | Description |
| --- | --- | --- | --- |
| `inline` | `"auto"` | `"auto"`, `"never"` | `auto` draws pictures inline when the terminal supports Sixel or the Kitty graphics protocol. `never` always draws the approximation. File-only. |

## Example

```toml
[basins]
enabled = ["AL"]

[units]
preset = "us"

[watchlist]
ndbc = ["41010", "41004"]
coops = ["8723214"]

[alerts]
bell = true
```
