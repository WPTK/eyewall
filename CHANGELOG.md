# Changelog

## [0.7.0] - 2026-10-31

### Changed

- Replace the Graphics tab placeholder with the image gallery ([`COMMIT`](https://github.com/WPTK/eyewall/commit/COMMIT), [#PR](https://github.com/WPTK/eyewall/pull/PR))

- Remove the sparkline strip from the buoy detail screen and give its height to the charts ([`COMMIT`](https://github.com/WPTK/eyewall/commit/COMMIT), [#PR](https://github.com/WPTK/eyewall/pull/PR))
- Show the buoy's wave height once, as `--`, when it reports no waves, and show the whole station name in the title ([`COMMIT`](https://github.com/WPTK/eyewall/commit/COMMIT), [#PR](https://github.com/WPTK/eyewall/pull/PR))

### Added

- Add the graphics gallery and the `g` screen: the cone, wind probabilities at 34, 50 and 64 kt, arrival times, surge watch and warning and peak surge, and the GEOCOLOR, air mass and infrared stills and loops, each shown with its address ([`COMMIT`](https://github.com/WPTK/eyewall/commit/COMMIT), [#PR](https://github.com/WPTK/eyewall/pull/PR))
- Add inline images through Sixel or the Kitty graphics protocol when the terminal supports them, probed once before the app starts ([`COMMIT`](https://github.com/WPTK/eyewall/commit/COMMIT), [#PR](https://github.com/WPTK/eyewall/pull/PR))
- Add a fallback that draws images in colored half blocks, braille or ASCII at the terminal's color depth, and trims the legend off NHC cone graphics ([`COMMIT`](https://github.com/WPTK/eyewall/commit/COMMIT), [#PR](https://github.com/WPTK/eyewall/pull/PR))
- Add satellite loops that decode one frame at a time, play at up to 10 frames per second and step with `[` and `]` ([`COMMIT`](https://github.com/WPTK/eyewall/commit/COMMIT), [#PR](https://github.com/WPTK/eyewall/pull/PR))
- Add `o` to open an image's address in the browser and `y` to copy it, with a message when no browser or clipboard is available ([`COMMIT`](https://github.com/WPTK/eyewall/commit/COMMIT), [#PR](https://github.com/WPTK/eyewall/pull/PR))
- Add image fetching to the data sources, size-capped and conditional, and the recorded Erin cones to the replay ([`COMMIT`](https://github.com/WPTK/eyewall/commit/COMMIT), [#PR](https://github.com/WPTK/eyewall/pull/PR))

[0.7.0]: https://github.com/WPTK/eyewall/releases/tag/v0.7.0

## [0.6.0] - 2026-10-31

### Changed

- Poll the watchlisted buoys and tide gauges when no storm is active, so the outlook watchlist fills on a quiet day ([`621a924`](https://github.com/WPTK/eyewall/commit/621a924d300690cd79719b02b2c03f0446521a0f), [#13](https://github.com/WPTK/eyewall/pull/13))
- Make the outlook watchlist a station table that opens a buoy's charts with Enter ([`54018ae`](https://github.com/WPTK/eyewall/commit/54018aec8c45d07bd5affc8c6298416447843097), [#13](https://github.com/WPTK/eyewall/pull/13))
- Show "not reporting" in the nearest-buoys strip for stations that have gone silent ([`54018ae`](https://github.com/WPTK/eyewall/commit/54018aec8c45d07bd5affc8c6298416447843097), [#13](https://github.com/WPTK/eyewall/pull/13))
- Color the buoy and tide gauge marks on the map by reported wind and dim them when stale ([`54018ae`](https://github.com/WPTK/eyewall/commit/54018aec8c45d07bd5affc8c6298416447843097), [#13](https://github.com/WPTK/eyewall/pull/13))

### Added

- Add the Buoys tab with distance, wind bands at 34, 50 and 64 kt, falling-pressure flags, wave height, water temperature, age and closest approach ([`54018ae`](https://github.com/WPTK/eyewall/commit/54018aec8c45d07bd5affc8c6298416447843097), [#13](https://github.com/WPTK/eyewall/pull/13))
- Add the Tides tab with observed and predicted water level and the residual ([`54018ae`](https://github.com/WPTK/eyewall/commit/54018aec8c45d07bd5affc8c6298416447843097), [#13](https://github.com/WPTK/eyewall/pull/13))
- Add the buoy detail screen with Sparklines, braille charts of pressure, wind with gust and wave height over 24, 48 and 72 hours, the latest observation and the interval extremes from the supplemental file ([`54018ae`](https://github.com/WPTK/eyewall/commit/54018aec8c45d07bd5affc8c6298416447843097), [#13](https://github.com/WPTK/eyewall/pull/13))
- Add the watchlist screen, the `/` station search and pinning with `p`, saved to the config file ([`54018ae`](https://github.com/WPTK/eyewall/commit/54018aec8c45d07bd5affc8c6298416447843097), [#13](https://github.com/WPTK/eyewall/pull/13))
- Add the settings screen for poll intervals, units, basins, nearby radii, alert rules and glyph set, saved to the TOML config ([`54018ae`](https://github.com/WPTK/eyewall/commit/54018aec8c45d07bd5affc8c6298416447843097), [#13](https://github.com/WPTK/eyewall/pull/13))
- Add 6-minute tide predictions to the live and replay sources and the supplemental file to the data source protocol ([`621a924`](https://github.com/WPTK/eyewall/commit/621a924d300690cd79719b02b2c03f0446521a0f), [#13](https://github.com/WPTK/eyewall/pull/13))
- Add Pilot tests for the new screens and snapshot tests for the Buoys tab, Tides tab, buoy detail, watchlist and settings ([`54018ae`](https://github.com/WPTK/eyewall/commit/54018aec8c45d07bd5affc8c6298416447843097), [#13](https://github.com/WPTK/eyewall/pull/13))

[0.6.0]: https://github.com/WPTK/eyewall/releases/tag/v0.6.0

## [0.5.0] - 2026-10-31

### Changed

- Launch the Textual app from `python -m eyewall`, live or with `--replay` and `--demo`, in place of the "not built yet" stub ([`a863041`](https://github.com/WPTK/eyewall/commit/a863041e0689bb8b433cda1f8ad66d2fc918d66d), [#12](https://github.com/WPTK/eyewall/pull/12))

### Added

- Add the storm dashboard: the storm list by basin, the map with cone, track, forecast points, wind radii and warning segments, and the headline, warnings, wind, surge and buoy panels, which fold into tabs below 110 columns ([`a863041`](https://github.com/WPTK/eyewall/commit/a863041e0689bb8b433cda1f8ad66d2fc918d66d), [#12](https://github.com/WPTK/eyewall/pull/12))
- Add the map widget over the renderer, with layer toggles, zoom, pan, fit to the cone and the 10 m coastline once zoomed in ([`a863041`](https://github.com/WPTK/eyewall/commit/a863041e0689bb8b433cda1f8ad66d2fc918d66d), [#12](https://github.com/WPTK/eyewall/pull/12))
- Add the storm detail screen with Summary, Forecast, Public Advisory (TCP and TCM toggle), Discussion, Wind Probabilities, Warnings and History tabs ([`a863041`](https://github.com/WPTK/eyewall/commit/a863041e0689bb8b433cda1f8ad66d2fc918d66d), [#12](https://github.com/WPTK/eyewall/pull/12))
- Add the tropical weather outlook screen with the watchlist, the alert log, the help screen, the layer menu and toasts from alert events ([`a863041`](https://github.com/WPTK/eyewall/commit/a863041e0689bb8b433cda1f8ad66d2fc918d66d), [#12](https://github.com/WPTK/eyewall/pull/12))
- Add replay transport keys (pause, speed, previous and next advisory) and a status bar with per-feed freshness and the next poll ([`a863041`](https://github.com/WPTK/eyewall/commit/a863041e0689bb8b433cda1f8ad66d2fc918d66d), [#12](https://github.com/WPTK/eyewall/pull/12))
- Add Pilot journey tests, SVG snapshot tests for the dashboard, a detail tab and the outlook, and launch tests for the command line ([`0c7cab9`](https://github.com/WPTK/eyewall/commit/0c7cab9f9fd9520440b9264488af804d06516a05), [#12](https://github.com/WPTK/eyewall/pull/12))

[0.5.0]: https://github.com/WPTK/eyewall/releases/tag/v0.5.0

## [0.4.0] - 2026-10-31

### Changed

- Gate the api.weather.gov text fallback behind a `fallback` switch and validate its product list with the ETag ([`0af5283`](https://github.com/WPTK/eyewall/commit/0af528334b37b402179c67ef1a4649cadfda6143), [#11](https://github.com/WPTK/eyewall/pull/11))

### Added

- Add the `DataSource` protocol with a live source over a disk cache that serves the last responses and marks feeds stale when the network fails ([`46beb4c`](https://github.com/WPTK/eyewall/commit/46beb4c5d095deb32e7d7ad796714cf3424541ed), [#11](https://github.com/WPTK/eyewall/pull/11))
- Add a replay source that serves a recorded storm on a virtual clock, the bundle format, `scripts/record_storm.py` and a trimmed Hurricane Erin recording that ships as the demo ([`46beb4c`](https://github.com/WPTK/eyewall/commit/46beb4c5d095deb32e7d7ad796714cf3424541ed), [#11](https://github.com/WPTK/eyewall/pull/11))
- Add the multi-feed poller with freshness, exponential backoff, away mode and refetching of a storm's products only when its advisory changes ([`4490d7f`](https://github.com/WPTK/eyewall/commit/4490d7f010e870a032803f5e9a5cc96edc64f259), [#11](https://github.com/WPTK/eyewall/pull/11))
- Add the store, the event diffs (storms, advisories, classification, watches and warnings, discussions, outlooks, buoy thresholds and silence) and the alert rules with a persisted seen set ([`4490d7f`](https://github.com/WPTK/eyewall/commit/4490d7f010e870a032803f5e9a5cc96edc64f259), [#11](https://github.com/WPTK/eyewall/pull/11))
- Add the `--replay`, `--demo`, `--headless`, `--until` and `--state-dir` flags and a live source spot-check script ([`4490d7f`](https://github.com/WPTK/eyewall/commit/4490d7f010e870a032803f5e9a5cc96edc64f259), [#11](https://github.com/WPTK/eyewall/pull/11))
- Add tests for the cache, sources, events, alerts, poller and the headless replay ([`a8f8917`](https://github.com/WPTK/eyewall/commit/a8f891788d48659fc59742dcf52b2148a5f33577), [#11](https://github.com/WPTK/eyewall/pull/11))

### Fixed

- Fix parsing of advisory headings that end in `...RESENT` and add the archive kinds for intermediate advisories ([`0af5283`](https://github.com/WPTK/eyewall/commit/0af528334b37b402179c67ef1a4649cadfda6143), [#11](https://github.com/WPTK/eyewall/pull/11))

[0.4.0]: https://github.com/WPTK/eyewall/releases/tag/v0.4.0

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
