# eyewall

A terminal app that tracks tropical cyclones with free NOAA data, and shows the buoys and tide gauges near each storm.

eyewall follows storms in the Atlantic, East Pacific and Central Pacific. For each one it will show the National Hurricane
Center advisory and discussion, the forecast track and cone, watches and warnings, wind radii and probabilities, and NOAA's
graphics. It pairs that with live readings from National Data Buoy Center buoys and CO-OPS tide gauges near the storm's
path, with pressure and wind traces, and it alerts you when NOAA posts something new.

Between storms it shows the tropical weather outlook and a watchlist of buoys you choose. A replay mode runs a recorded
storm (Hurricane Erin, 2025) so every screen can be tried in the off-season.

## Status

Pre-alpha, version 0.0.1. The project is built in milestones, each released as its own `0.y.0`; the interface arrives in
0.5.0. See `docs/plan.md` for the design and `docs/milestones/` for what each release adds.

## Try it

Python 3.12 or newer.

```bash
git clone https://github.com/WPTK/eyewall
cd eyewall
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"      # Windows: .venv\Scripts\python
.venv/bin/python -m eyewall --version
```

## Data

Everything comes from public NOAA feeds that need no key: NHC and CPHC advisories and GIS products, NWS alerts, NDBC
buoys, CO-OPS tide gauges and NESDIS satellite imagery. The feeds, their formats and how often eyewall polls them are in
`docs/data-sources.md`.

eyewall is not an official source of warnings. For decisions about life and property, use the National Hurricane Center
and your local National Weather Service office.

## License

MIT. Map outlines come from Natural Earth, which is in the public domain.
