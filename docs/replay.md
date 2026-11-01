# Replay

Most of the year no tropical cyclone is active, so eyewall can replay a recorded storm instead of reading live feeds.
The bundled recording is Hurricane Erin (2025, AL052025), from 19 August 03:00Z to 21 August 12:00Z.

```powershell
eyewall --demo                          # the interface, driven by the recording
eyewall --replay path\to\bundle         # your own recording
eyewall --demo --headless --until +6h   # no interface: print the events the first six hours produce
eyewall --demo --summary --until +20h  # no interface: the plain-sentence summary at that moment
```

## How it works

A replay is a `ReplaySource` (`src/eyewall/sources/replay.py`) behind the same `DataSource` protocol the live source
implements, so the poller, the store, the alert engine and the interface cannot tell them apart. The source owns a
`VirtualClock` (`src/eyewall/clock.py`) that starts at the bundle's first moment. Each call answers with what NOAA would
have published at the clock's current time: the newest advisory at or before it, the best track rows up to it, the buoy
and tide gauge rows up to it. Time advances only when the replay is playing, so a paused replay is still.

With no storm active, the live app offers the bundled recording: press `R` on the map screen.

In the interface the Replay keys are: space pauses and resumes, `<` and `>` slow down and speed up, `[` and `]` jump to
the previous and next advisory. Headless runs step the clock between polls and stop at `--until` (`+12h`, `+90m`, or an
ISO timestamp, counted from the bundle start).

A replay never reads or writes your real seen-alert set; it keeps none unless you pass `--state-dir`.

## What a bundle holds

A bundle is a directory. The layout is documented at the top of `src/eyewall/sources/bundle.py`: a `manifest.toml`, the
best track, each advisory's text products and GIS zips, the recorded buoys' historical rows, the tide gauges' datagetter
answers and a few cone stills. The replay serves no outlook, invests, alerts or satellite imagery.

## Recording another storm

`scripts/record_storm.py` builds a bundle from NOAA's archives. It needs the network, waits between requests, and takes a
few minutes.

```powershell
.venv\Scripts\python scripts\record_storm.py AL052025 --from 2025-08-18T09:00 --to 2025-08-21T03:00 `
    --out recordings\erin --stations auto --tide-gauges auto
```

- `storm_id` is the NHC id, such as `AL052025`. `--from` and `--to` are UTC and bound the replay.
- `--stations auto` picks the buoys within 300 nautical miles of the best track that have data in the window, nearest
  first, up to `--max-stations` (8). Give a comma separated list of NDBC ids to choose them yourself.
- `--tide-gauges auto` does the same for CO-OPS water level gauges within 250 nautical miles (`--max-gauges`, 3); use
  `none` to leave them out.
- `--track-hours` (72) is how much best track before `--from` is kept; `--history-hours` (24) is the same for buoy rows.
- `--graphics` (2) is how many cone stills to keep, `--name` sets the bundle name, `--delay` the pause between requests.

Then replay it with `eyewall --replay recordings\erin`. Recording older seasons works as long as NHC's archive pages and
the ATCF archive still hold the storm.
