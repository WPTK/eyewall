# eyewall

eyewall is a terminal app that tracks tropical cyclones in the Atlantic, East Pacific and Central Pacific. It reads free
NOAA feeds, so it needs no account or key. It opens on a map of the storms, says in plain words what each one is doing,
and shows the buoys and tide gauges near it.

![The main screen at 140x42: the map with the forecast cone and track, and beside it the storm cards, watches and warnings, and nearby stations](docs/images/dashboard.png)

eyewall is not an official forecast or warning. For decisions about life or property, follow the National Hurricane
Center and your local emergency officials.

## What you see

The map is the first screen, at every terminal size. Active storms are drawn on it with their forecast cone, track, wind
rings and the watches and warnings along the coast. Beside it (or under it, on a small terminal) are a card for each
named storm, the watches and warnings in the National Hurricane Center's own words, what NHC is watching in the outlook,
and the stations near the storm. With no storm active it says so in a sentence, shows the outlook areas and your own
stations, and offers a replay of Hurricane Erin.

From the map you reach six more screens. Each is a click or a key away, and `Esc` goes back.

- **Storm** (`Enter` on a storm): a lead sentence, the watches and warnings and what they mean, wind, size, the forecast,
  the chance of strong wind, when the next advisory is due and how old the data is.
- **NHC text** (`t`): the public advisory, discussion, forecast/advisory, wind chances, outlook and past track, with the
  issue time, the advisory number and a banner when the text is out of date.
- **Buoys and gauges** (`b`): two tabs, the stations near the storm and the stations you follow. Sort by distance, wind
  or name, and follow the ones you care about.
- **Station** (open a buoy or tide gauge): a plain sentence, trends, pressure, wind and wave charts over 24, 48 or 72
  hours, and a table of readings.
- **Pictures** (`g`): NOAA's cone and satellite pictures for the storm, with loops.
- **Help** (`?`): every key, and what the top bar says about the health of the feeds.

![Pressure, wind and wave charts for buoy 41001 with its latest readings](docs/images/buoy.png)

## Mouse and keyboard

Everything can be clicked: a storm, a buoy or gauge on the map (with a chooser when marks overlap), a card's `open >`
link, a row in a list, the breadcrumb in the top bar, every key in the footer and the feed-health slot. Drag the map to
pan it. Everything can also be done from the keyboard. `Ctrl+P` opens a menu that lists every screen, action, storm and
station, so you can find anything by typing part of its name.

| Key | What it does |
| --- | --- |
| `?` | Help: every key |
| `Ctrl+P` | The menu: every screen, action, storm and station |
| `Esc`, `Backspace` | Go back one screen; close a dialog; leave the full-screen map |
| `q` | Quit, from the first screen only |
| `m` | Go to the map |
| `D` | Feed health: each feed, its age and the next refresh |
| `/` | Find a buoy or tide gauge by name or id |
| `g` | Pictures for the selected storm |
| `A` | The alert log |
| `S` | Settings |
| `r` | Refresh every feed now |
| `u` | Cycle the units |

On the map:

| Key | What it does |
| --- | --- |
| `j`, `k`, `Enter` | Previous or next storm; open its page |
| `1`, `2`, `3`, `a` | Atlantic, East Pacific, Central Pacific, all |
| `b` | Buoys and tide gauges near the storm (your stations when there is none) |
| `t` | The NHC text for the storm (the outlook when there is none) |
| `O` | The tropical weather outlook text: each area and its chances |
| `M` | Full-screen map; `Esc` leaves it |
| `R` | Replay Hurricane Erin (only when nothing is active) |
| `+`, `-` | Zoom in and out |
| Arrow keys | Pan the map |
| `f`, `c` | Fit the storm, center on it |
| `n`, `N`, `Enter` | Step to the next or previous storm, buoy or gauge; open the marked one |
| `l` | Map layers |

On the other screens:

| Screen | Key | What it does |
| --- | --- | --- |
| Storm | `b`, `t`, `g` | Buoys and gauges, NHC text, pictures |
| Storm | `p` | The chance of storm-force wind at named places |
| Storm | `Left`, `Right` | Previous or next storm |
| NHC text | `Left`, `Right` | Previous or next product; Page Up and Page Down scroll |
| Buoys and gauges | `Enter` | Open the highlighted station |
| Buoys and gauges | `f`, `s`, `Tab` | Follow or stop following; change the order; switch tabs |
| Station | `f`, `m` | Follow or stop following; show the station on the map |
| Station | `Tab` | On a short screen, show the next chart |
| Station | `h`, `r`, `i` | 24, 48 or 72 hours; charts or readings; how buoy winds differ from the storm's |
| Pictures | `o`, `y` | Open the picture's address in a browser; copy it |
| Pictures | `[`, `]`, `Space` | Step through a loop; play or pause |

In a replay: `Space` pauses or resumes, `<` and `>` change the speed, and `[` and `]` step between advisories.

The footer shows the keys that work on the current screen and always ends with `? help`.

## Install

Standalone binaries for Windows, Linux (x86_64 and arm64) and macOS (Apple silicon and Intel) are on the
[releases page](https://github.com/WPTK/eyewall/releases). They need no Python and are not signed, so Windows and macOS
may warn on first run; `docs/install.md` covers that and the checksums.

With Python 3.12 or newer you can install from the repository:

```
pipx install git+https://github.com/WPTK/eyewall
```

Or from a clone:

```
python -m venv .venv
.venv/bin/python -m pip install -e .        # Windows: .venv\Scripts\python
.venv/bin/python -m eyewall --demo
```

`eyewall --selftest` checks an installation: it replays an hour of the bundled storm and prints `selftest ok`.

## First run

Use a terminal that draws Unicode, such as Windows Terminal, iTerm2, kitty or GNOME Terminal, at least 60 columns by 16
rows. At 80x24 the map fills the screen with a line about the storm and a line of warnings under it. At 100x30 or larger
the column of cards appears beside the map. A smaller terminal gets a message that says what size eyewall needs instead
of a broken screen.

```
eyewall --demo
```

Most of the year nothing is active, so `--demo` replays a recording of Hurricane Erin (August 2025) and is the quickest
way to look around. Press `Enter` on the storm, then `t`, `b` and `g` to visit the other screens. Run `eyewall` with no
flags for live data. If no storm is active it says so, and `R` starts the same Erin replay.

## Command line

```
eyewall                           # live data
eyewall --demo                    # the bundled Erin recording
eyewall --replay DIR              # a recording of your own
eyewall --basin AL                # only the Atlantic; repeat the flag for EP and CP
eyewall --summary                 # print what is happening in plain sentences, then exit
eyewall --glyphs ascii            # plain symbols for terminals that cannot draw braille
eyewall --headless --until +12h   # no interface; print events as they happen
```

Other flags: `--config PATH` and `--no-config` for the settings file, `--state-dir DIR` for where seen events are kept,
`--version`, and `--help` for the full list.

`eyewall --summary` prints the current storms, their watches and warnings, the nearby buoy and tide gauge reports and
the outlook as plain sentences, once, and exits. It needs no terminal interface, so it works in a script, over SSH or
with a screen reader. When a feed could not be fetched it says which data is unavailable, and exits with status 1,
instead of reporting a quiet day. It also works with `--demo` and `--replay`.

## Replay

`eyewall --demo` and `eyewall --replay DIR` drive the same screens from a recording, with the clock under your control.
`docs/replay.md` explains how replays work and how to record another storm.

## Colour

Colour never carries a meaning alone. Every colour cue also has a word, a glyph, a line pattern or bold, underline or
reverse video, so the screens read the same with `NO_COLOR` set: wind rings are dotted, dashed and solid for 34, 50 and
64 knots, watches and warnings use different line styles, and the selected row has a pointer. The map key names each
pattern. Use `--glyphs ascii` on terminals that cannot draw braille.

Inline pictures need Sixel or the Kitty graphics protocol; elsewhere eyewall draws an approximation.

## Data sources

Everything comes from public NOAA services:

- NHC and CPHC: advisories, forecast discussions, GIS products and storm graphics
- NWS: watches, warnings and other alerts
- NDBC: buoy observations
- CO-OPS: tide gauge water levels
- NESDIS: satellite imagery

None of them needs a key. eyewall identifies itself with a User-Agent that carries no personal details, makes
conditional requests, honors `Retry-After` and polls no faster than each feed allows. It fetches zips and pictures only
when a storm's advisory number changes. The top bar shows how fresh the data is, and `D` lists each feed with its age.
`docs/data-sources.md` lists the feeds, their formats and the polling cadence. A daily workflow checks that each feed
still parses.

## Documentation

- `docs/install.md`: binaries, pipx, settings and the config file
- `docs/replay.md`: replaying and recording storms
- `docs/data-sources.md`: the NOAA feeds
- `docs/development.md`: setup, checks, tests and releases

Bugs and ideas go in the [issues](https://github.com/WPTK/eyewall/issues).

## License

MIT. The map outlines come from Natural Earth, which is in the public domain.
