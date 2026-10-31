# Changelog

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
