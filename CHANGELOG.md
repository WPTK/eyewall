# Changelog

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
