# Changelog

## [0.3.0] - 2026-10-31

### Added

- Add the terminal map renderer: viewport projection, a braille, half-block and ASCII canvas, a base map, and layers for cones, tracks, watches and warnings, wind radii, buoys and tide gauges ([`6e5b4b8`](https://github.com/WPTK/eyewall/commit/6e5b4b8300d74e757c50a8b2eb17ad4f73d64066), [#2](https://github.com/WPTK/eyewall/pull/2))
- Add vendored Natural Earth map data for the basin and the script that rebuilds it byte for byte ([`4f8e12b`](https://github.com/WPTK/eyewall/commit/4f8e12b7d363c719535e72c65716879d957cd125), [#2](https://github.com/WPTK/eyewall/pull/2))
- Add line charts for buoy and tide gauge traces ([`6fa516c`](https://github.com/WPTK/eyewall/commit/6fa516c95c4d60dbdc310db9d47b0e8c41d61dae), [#2](https://github.com/WPTK/eyewall/pull/2))
- Document the renderer interface and the pinned map data source in the plan ([`6f44c76`](https://github.com/WPTK/eyewall/commit/6f44c76b1877f614058c7c8d61f30ce80379c688), [#2](https://github.com/WPTK/eyewall/pull/2))

[0.3.0]: https://github.com/WPTK/eyewall/releases/tag/v0.3.0

## [0.2.0] - 2026-10-31

### Changed

- Correct the NDBC historical file layout, catalog flags and CO-OPS error behaviour in the data-source reference ([750882c](https://github.com/WPTK/eyewall/commit/750882ca3183a83391bdaa9515e91e42b6547864), [#1](https://github.com/WPTK/eyewall/pull/1))

### Added

- Add parsers for the NDBC station catalog, latest observations, station files, supplemental and wave files and historical files ([8511324](https://github.com/WPTK/eyewall/commit/8511324257d51358f6f8a3e1456727a9a0573d41), [#1](https://github.com/WPTK/eyewall/pull/1))
- Add an NDBC client that sends conditional requests and treats a missing station file as not reporting ([bbddc78](https://github.com/WPTK/eyewall/commit/bbddc783d42dd8a89dcdfe30a43b2ad6c8355bac), [#1](https://github.com/WPTK/eyewall/pull/1))
- Add CO-OPS station lists, water level, predictions, wind and air pressure parsers and a one-request-per-gauge client ([4fcb3cd](https://github.com/WPTK/eyewall/commit/4fcb3cd3827f263c3aea9ce7feae1237f06bf7c2), [#1](https://github.com/WPTK/eyewall/pull/1))
- Add nearby-station selection by distance to a storm's center and forecast track, with closest approach and time to it ([a4cfec4](https://github.com/WPTK/eyewall/commit/a4cfec432f037737c4c5b6452549e7aa2abc9eef), [#1](https://github.com/WPTK/eyewall/pull/1))
- Add station trends: pressure tendency, wind and gust trend, observation age, silent flag and interval extremes ([15c2654](https://github.com/WPTK/eyewall/commit/15c2654425a85ca3e12cee89f5582577593e4438), [#1](https://github.com/WPTK/eyewall/pull/1))
- Add scripts to record observation fixtures and spot-check the live NDBC and CO-OPS services ([919fda8](https://github.com/WPTK/eyewall/commit/919fda8a97d77a80968c0dcaa88c46fa0aa9e41c), [#1](https://github.com/WPTK/eyewall/pull/1))

[0.2.0]: https://github.com/WPTK/eyewall/releases/tag/v0.2.0

## [0.1.0] - 2026-10-31

_Initial release._

### Added

- Add `NhcClient`, which fetches each NHC, CPHC and NWS feed through the shared HTTP helper with conditional requests, falls back from tgftp to api.weather.gov for text, and drops text that is not for a storm's current advisory ([`d41da00`](https://github.com/WPTK/eyewall/commit/d41da00), [#3](https://github.com/WPTK/eyewall/pull/3))
- Add a parser for CurrentStorms.json that keys storms by lower-case id, coerces the feed's string numbers, keeps movement in mph and carries intermediate advisory numbers ([`d5adc90`](https://github.com/WPTK/eyewall/commit/d5adc90), [#3](https://github.com/WPTK/eyewall/pull/3))
- Add parsers for forecast advisories, public advisories, discussions, wind speed probabilities and tropical weather outlooks, including dissipated, post-tropical, remnant, potential and east-longitude forms ([`6bd5531`](https://github.com/WPTK/eyewall/commit/6bd5531), [#3](https://github.com/WPTK/eyewall/pull/3))
- Add parsers for the forecast, wind radii, best track and outlook shapefile zips, with the cone, TCWW watch and warning codes and wind radii by quadrant, tolerating missing layers ([`5ca8c84`](https://github.com/WPTK/eyewall/commit/5ca8c84), [#3](https://github.com/WPTK/eyewall/pull/3))
- Add a parser for ATCF best track files, including invests, and for the `btk` directory listing ([`bfe366e`](https://github.com/WPTK/eyewall/commit/bfe366e), [#3](https://github.com/WPTK/eyewall/pull/3))
- Add parsers for api.weather.gov tropical alerts and product lists, forecast graphics links and NESDIS floater listings ([`6406b04`](https://github.com/WPTK/eyewall/commit/6406b04), [#3](https://github.com/WPTK/eyewall/pull/3))
- Add frozen dataclass models for storms, forecasts, advisories, wind radii, watches and warnings, outlooks, graphics and best tracks ([`c4a1e9e`](https://github.com/WPTK/eyewall/commit/c4a1e9e), [#3](https://github.com/WPTK/eyewall/pull/3))
- Add storm id, product bin and advisory number handling, every feed URL, header time conversion and the storm provider protocol ([`caed961`](https://github.com/WPTK/eyewall/commit/caed961), [#3](https://github.com/WPTK/eyewall/pull/3))
- Add `scripts/spot_check_nhc.py`, which fetches and parses every live NHC endpoint once and prints a summary ([`e2de20a`](https://github.com/WPTK/eyewall/commit/e2de20a), [#3](https://github.com/WPTK/eyewall/pull/3))
- Add `scripts/record_fixtures.py` and fixtures recorded from Hurricane Erin (2025), Potential Tropical Cyclone Eight (2024) and the 2026 season ([`2f76207`](https://github.com/WPTK/eyewall/commit/2f76207), [#3](https://github.com/WPTK/eyewall/pull/3))
- Add the observed NHC feed details to the data sources reference, correcting tgftp file names, the CP b-deck location and the outlook zip layout ([`c8c2d7a`](https://github.com/WPTK/eyewall/commit/c8c2d7a), [#3](https://github.com/WPTK/eyewall/pull/3))

[0.1.0]: https://github.com/WPTK/eyewall/releases/tag/v0.1.0
