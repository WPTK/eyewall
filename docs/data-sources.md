# Data sources

Every feed below is public and keyless. Formats and URLs were checked against the live services on 2026-10-31, a day with no active storms, so a few details (marked in the text) are confirmed during the first live storm. Milestone sessions should treat this file as the reference and correct it when a feed disagrees.

Every request sends `User-Agent: eyewall/<ver> (+https://github.com/WPTK/eyewall)` (api.weather.gov returns 403
without one). Conditional GETs (`ETag`/`If-Modified-Since`; NDBC returned 304s) and gzip everywhere. Raw
payloads cached under `platformdirs.user_cache_dir("eyewall")` so startup paints at once and offline shows
last-known data marked stale. Zips and images are fetched only when a storm's advisory number changes.

## Storms (NHC / CPHC / NWS)

| Feed | URL | Used for | Cadence |
|---|---|---|---|
| CurrentStorms | `https://www.nhc.noaa.gov/CurrentStorms.json` | active storms in all basins, with product and GIS links. `{"activeStorms": []}` when quiet | 5 min (CDN max-age 300) |
| TCM forecast/advisory | `https://tgftp.nws.noaa.gov/data/raw/wt/wtnt2{n}.knhc.tcm.at{n}.txt`, `wtpz2{n}.knhc.tcm.ep{n}.txt`, `wtpa2{n}.phfo.tcm.cp{n}.txt` (`{n}` is the bin index 1 to 5, so AT3 is `wtnt23.knhc.tcm.at3.txt`) | parsed: center, max wind/gust, pressure, movement, 34/50/64 kt radii by quadrant, forecast + outlook points | on `lastUpdate` change |
| TCP public advisory, TCD discussion, TCU update, PWS wind probabilities | same tree: `wt/wtnt3{n}.knhc.tcp.at{n}.txt` TCP, `wtnt4{n}…tcd` TCD, `wtnt6{n}…tcu` TCU, `fo/font1{n}.knhc.pws.at{n}.txt` PWS (EP `wtpz`/`fopz`, CP `wtpa`/`fopa` with `phfo`); TCU can also come from api.weather.gov | text views; headline and watch/warning text from the TCP, key messages from the TCD (the TCP only points to them); PWS table parsed | on `lastUpdate` change |
| TWO outlook | `ab/abnt20.knhc.two.at.txt`, `ab/abpz20.knhc.two.ep.txt`, `ac/acpn50.phfo.two.cp.txt` | outlook text per basin | 30 min |
| Text fallback | `https://api.weather.gov/products/types/{TCM\|TCP\|TCD\|TCU\|PWS\|TWO}/locations/{AT1\|EP2\|CP3\|AT\|EP\|CP}` → `/products/{id}` `.productText` | when tgftp fails; location is the **bin**, never KNHC/PHFO | on demand |
| US watches/warnings with geometry | `https://api.weather.gov/alerts/active?event=Hurricane Warning,Hurricane Watch,Tropical Storm Warning,Tropical Storm Watch,Storm Surge Warning,Storm Surge Watch,Hurricane Force Wind Warning,Extreme Wind Warning,Tropical Cyclone Statement` | WW panel with affected zones; cross-checked against TCP text | 5 min while a storm threatens US land |
| Forecast GIS (shapefiles) | `forecastTrack.zipFile` from CurrentStorms, pattern `https://www.nhc.noaa.gov/gis/forecast/archive/{id}_5day_{adv}.zip` / `_latest.zip`; layers `*_5day_pts` (TAU, MAXWIND, GUST, DATELBL, TCDVLP), `*_5day_lin`, `*_5day_pgn` (cone), `*_ww_wwlin` (TCWW = TWA/TWR/HWA/HWR) | cone polygon, forecast points, coastal watch/warning segments | on `advNum` change |
| Wind radii GIS | `forecastWindRadiiGIS.zipFile`, pattern `{id}_fcst_{adv}.zip`; `initialWindExtent` | 34/50/64 kt radii polygons (initial and forecast) | on `advNum` change |
| Best track | ATCF b-deck `https://ftp.nhc.noaa.gov/atcf/btk/b{al\|ep\|cp}{nn}{yyyy}.dat` (CP storms are `bcp…` files in the same directory; `btk/cphc/` is a stale folder from 2014); `bestTrackGIS` zip as alternative; archive `atcf/archive/{yyyy}/b….dat.gz`. The directory page lists every file, which is how active invests are found | past track colored by intensity; invests are numbers 90–99 (80–89 are training, ignored) | on `lastUpdate` change |
| ATCF indexes | `atcf/index/master_list.txt`, `index/{AL,EP,CP}_storms.txt.nhc` | id ↔ name sanity, replay tooling | daily / dev |
| Invests and outlook areas | `https://www.nhc.noaa.gov/xgtwo/gtwo_shapefiles.zip` (`gtwo_areas_<yyyymmddhhmm>`, `gtwo_lines_…`, `gtwo_points_…` with `BASIN` (`Atlantic` or `Pacific`), `AREA`, `PROB2DAY` (`80%`), `RISK2DAY` (`High`), `PROB7DAY`, `RISK7DAY`; one combined zip for all basins since May 2026) + invest b-decks. The zip has no invest numbers | invests on the storm list and outlook map; they are not in CurrentStorms.json | 30 min |
| Surge GIS | `stormSurgeWatchWarningGIS.kmlFile`, `potentialStormSurgeFloodingGIS` (links from CurrentStorms) | surge WW polylines parsed from KML; inundation GeoTIFFs link-only | on `advNum` change |
| Graphics | `forecastGraphics.url` landing page (links to cone PNG/GIF, wind probabilities, arrival time, surge); `storm_graphics/api/{ID}_CONE_latest.kmz` | graphics gallery; exact PNG/GIF URL patterns are learned from the landing page during the first active storm (the `refresh/…+png` pattern 404s once a storm ends). On a quiet day the landing page links only `/graphics/notready.jpg`. Archived storms have `archive/{yyyy}/{NAME}_graphics.php?product=5day_cone_with_line_and_wind` pages listing `graphics/AL052025/AL052025_5day_cone_with_line_and_wind_{adv}.png` per advisory | on `advNum` change |
| Satellite loops | `https://cdn.star.nesdis.noaa.gov/FLOATER/data/{ID}/{GEOCOLOR\|Sandwich\|AirMass\|DayConvection\|01..16}/` listing; latest still `…1000x1000.jpg`, loops `…-ABI-{ID}-{product}-1000x1000.gif` | newest still and loop per storm. `FLOATER/data/` lists storm directories, a storm directory lists products (`01`..`16`, `AirMass`, `GEOCOLOR`...) and a product directory lists every still and loop (1 MB for a 12 day storm); the files are `{yyyyddd}{hhmm}_GOES19-ABI-FL-GEOCOLOR-{ID}-1000x1000.jpg` (year, day of year, UTC), ranged loops `{start}-{end}-ABI-{ID}-GEOCOLOR-1000x1000.gif`, the full loop `{ID}-GEOCOLOR-1000x1000.gif` and the rolling `latest.jpg` | 10 min |
| NHC archive | `https://www.nhc.noaa.gov/archive/{yyyy}/{al05}/al052025.{fstadv\|public\|discus}.{NNN}.shtml` + the GIS archive zips above | replay bundles only | dev script |

## Observations (NDBC / CO-OPS)

| Feed | URL | Used for | Cadence |
|---|---|---|---|
| NDBC station catalog | `https://www.ndbc.noaa.gov/activestations.xml` (1352 stations, 865 `met="y"`) | id, lat/lon, name, type, reported-in-last-8h flags | 24 h, cached |
| NDBC latest obs, all stations | `https://www.ndbc.noaa.gov/data/latest_obs/latest_obs.txt` (~98 KB, ~826 stations, obs < 2 h old) | one fetch for every station's newest met obs | 10 min (CDN max-age 600) |
| NDBC 5-day station files | `https://www.ndbc.noaa.gov/data/5day2/{ID}_5day.txt` (~66 KB), `_5day.supl` (interval min pressure, peak wind with times), `_5day.spec` (waves) | history, charts and trends for nearby/pinned stations | 10 min, staggered, ≤4 in flight |
| NDBC 45-day files | `https://www.ndbc.noaa.gov/data/realtime2/{ID}.txt` (~600 KB) | only when the user asks for 72 h+ | on demand |
| NDBC historical | `data/historical/stdmet/{id}h{yyyy}.txt.gz` (lowercase id, no PTDY, `99.0`/`999` fills); `data/stdmet/{Mon}/{id}{M}{yyyy}.txt.gz` (e.g. `Aug/4101082025.txt.gz`) | replay bundles only | dev script |
| CO-OPS stations | `https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=waterlevels` (302; `?type=met` 314); longitude field is `lng` | tide gauge catalog | 24 h, cached |
| CO-OPS data | `https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product={water_level\|predictions\|air_pressure\|wind}&station=…&datum=MLLW&units=english&time_zone=gmt&format=json&application=eyewall` with `date=latest\|recent` or `begin_date`/`range` | observed vs predicted water level (surge residual), wind, pressure near the storm | 6 min |
| Basemap | Natural Earth GeoJSON (nvkelso mirror): 50 m coastline 1.6 MB, 50 m admin-1 state lines 0.9 MB, admin-0 boundaries 0.7 MB, 110 m coastline 137 KB, 110 m land for dim fill | vendored, pre-simplified, no runtime download | dev script |

## Facts that shape the code (observed, not assumed)

- **CurrentStorms.json:** `id` lowercase (`"al052025"`), key everything by it; `binNumber` `AT1–5`/`EP1–5`/`CP1–5` is
  reused within a season and a storm crossing 140°W keeps its `ep` id but moves to a `CP` bin with HFO URLs.
  `classification` ∈ TD, STD, TS, HU, STS, PTC, PC, TY. `intensity`, `pressure` are **strings**; `latitude`
  `"17.1N"` strings with `latitudeNumeric`/`longitudeNumeric` twins; **`movementSpeed` is mph** (TCM is kt).
  Product objects carry `advNum` (`"018a"` for intermediates), `issuance`, `fileUpdateTime`, `url`; GIS objects
  can each be `null`; `peakSurgeKML` names its file `peakSurgeKMLFile`. The 2019 reference PDF is wrong on several of
  these.
- **Text products:** `.shtml` pages keep a dead storm's last advisory, so parsed text is checked against
  `lastUpdate`/`advNum` before replacing the current advisory.
- **TCM parsing:** anchor on `CENTER LOCATED NEAR`; forecast hours count from the synoptic time 3 h before the
  advisory; radii lines are omitted when a threshold does not apply; `OUTLOOK VALID` points carry only 50/34 kt
  radii; `…DISSIPATED` and `…POST-TROP/REMNT LOW` suffixes; longitudes flip to `E` near the dateline.
  Also observed: the center phrase is `HURRICANE`, `POST-TROPICAL CYCLONE`, `REMNANTS OF` or `POTENTIAL TROP CYCLONE`; fix
  suffixes include `…INLAND`, `…TROPICAL CYCLONE`, `…POST-TROP/EXTRATROP`; seas are `4 M SEAS` or `12 FT SEAS`; a radius of
  `0` means none in that quadrant while a missing line means the threshold does not apply; one product can mix W and E
  (`AT 04/1800Z CENTER WAS LOCATED NEAR 24.0N 179.2W` then `24.2N 180.0E`); a final advisory says `THIS IS THE LAST
  FORECAST/ADVISORY` and the wind probability product then has an empty table. A bin keeps the last advisory of the
  most recent storm to use it, so tgftp always has examples of the odd cases.
- **b-deck:** up to three lines per time (one per radii threshold), early rows `DB`/genesis (name `INVEST` or
  `GENESISnnn`), DIR/SPEED often 0, `E` longitudes possible (`1771E`), 0 for an unknown wind or pressure. OFCL forecast
  lives in the a-deck (stretch: model "spaghetti").
- **Shapefiles:** parsed with `pyshp` straight from the zip (`zipfile` + `shapefile.Reader(shp=…, dbf=…)`);
  intermediate advisories use an `A` suffix (`_5day_010A.zip`, ADVISNUM `10A`). Unknown numbers are `9999` (`MSLP`, `TCDIR`,
  `TCSPD` on every point after the first). Across the dateline the layers disagree: the track line and points continue
  west of -180 (`-182.3`), the cone continues east of 180, and radii polygons use either; eyewall wraps every vertex to
  (-180, 180]. The points layer spells the name out (`Hurricane Erin`), the other layers do not.
- **NDBC:** winds are m/s 8-minute (buoy) or 2-minute (C-MAN) averages, never equated with NHC's 1-minute kt.
  Missing is `MM` in realtime files but `99.0`/`999`/`9999` fills in historical and `.cwind` files. Parse by
  header name, not position (PTDY sits in different places in `latest_obs.txt` and `realtime2`). Waves are often
  `MM` in a `latest_obs` row; waves come from station files. Buoy cadence 10 min, waves at :20/:50, PTDY only on
  the hour, C-MAN hourly, ~20 min latency. Listed ≠ reporting (41001 recovered 2026-09-09; 42040, 42003,
  42019, 42020, 42059 dark): a 404 is normal and shown as "not reporting". C-MAN ids are lowercase in the XML
  and uppercase in file names; ids can be 7 characters.
- **CO-OPS:** `datum` required for water level (400 otherwise); values are strings; missing is `""`; 6-min data;
  6-minute requests span at most a month; they throttle heavy users, so one request per gauge per poll.
- **No published rate limits** on NHC or NDBC; NDBC asks to "limit retrievals to a minimal level". Cadences
  match CDN `max-age`. NDBC has no JSON API; the classic text endpoints remain documented and supported.
- **2026 season:** cones shrank 3–8 % and carry inland watches/warnings; CPHC operations run under NHC (PHFO
  headers stay); Gulf of America wording appears in text.
