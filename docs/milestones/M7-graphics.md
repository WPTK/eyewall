# M7 Graphics

## Goal

NOAA's graphics and satellite imagery in the terminal: inline where the terminal can show them, a readable approximation
everywhere else. Release 0.7.0.

## Depends on

M6 merged.

## Scope

- `render/images.py`: fetch PNG, GIF and JPEG with `eyewall.net`, open with Pillow. Choose the display path from the
  terminal and `[graphics] inline`: Sixel or the Kitty graphics protocol through `textual-image` when supported (Windows
  Terminal 1.22 and later does Sixel), otherwise the fallback. Import `textual_image.renderable` and `textual_image.widget`
  lazily, only here; they send terminal queries when imported with stdout on a TTY.
- The fallback: downsample with LANCZOS to the cell grid times two (half-block) or times (2, 4) (braille), apply a mild
  unsharp mask and auto-contrast, quantize to the terminal's color depth, and for NHC cone graphics crop the known margins so
  the legend does not waste cells.
- Animated GIFs (satellite loops): extract frames, play at up to 10 frames per second inline, and step with `[` and `]` in
  the fallback. Cap memory by decoding frames lazily.
- Graphics screen and the storm detail Graphics tab: a gallery of the links M1 produces (cone, wind probabilities at 34, 50
  and 64 kt, arrival time, surge watch and warning, peak surge) plus the NESDIS GEOCOLOR, air mass and infrared stills and
  newest loops. The selected image shows with its URL; `o` opens it in the browser, `y` copies the URL with Textual's clipboard.
- Graphics are fetched only when the storm's advisory number changes, and a satellite loop only when it is on screen. If you
  find the real `refresh/...` image URL patterns differ from the landing-page links, trust the links and update
  `docs/data-sources.md`.

## Out of scope

New graphics sources beyond NHC and NESDIS. Rendering inundation GeoTIFFs (link only).

## Done when

- In Windows Terminal, the cone and a GEOCOLOR still show inline; with `--glyphs ascii` or `inline = "never"` they show
  through the fallback and are still readable; a loop animates.
- Opening and copying URLs work. Tests cover the fallback pipeline (deterministic output for a small test image), frame
  stepping and the lazy-import rule (importing the core must not import `textual_image`).
- All checks in `CLAUDE.md` pass; version is 0.7.0 with its changelog entry; State after is filled in and the status in
  `docs/milestones/README.md` is updated.

## Verify

The commands in `CLAUDE.md`, then view the gallery in Windows Terminal and in a terminal without graphics support.

## State after

**What exists.**

- `render/images.py` (no Textual): `fetch_image` (eyewall's client, so the User-Agent, timeouts and the cache's
  conditional requests; refuses non-web addresses, anything that is not a PNG, GIF or JPEG by its first bytes, and more than
  24 MB), `Frames` (lazy frame decoding: a few decoded frames kept, a loop thinned to 240 frames, 36 million pixels at
  most), `FrameCursor` (play, pause, step and wrap), and the fallback `render_fallback` (LANCZOS to the cell grid times
  two, or times (2, 4) for braille, mild unsharp mask, auto-contrast, quantized to 24-bit, 256, 16 or no color, with
  `crop_cone` for the NHC cone graphic). `load_inline` is the only code that imports `textual_image`.
- `ui/gallery.py` (no Textual): the gallery list for a storm, in reading order: cone, wind probabilities at 34, 50 and 64
  kt, arrival times, surge watch and warning, peak surge, then the GEOCOLOR, air mass and infrared stills and loops.
  KMZ files are listed as link only.
- `ui/widgets/gallery.py` (`GalleryPanel`, `ImageView`), `ui/screens/graphics.py` (`GraphicsScreen`, key `g` on the
  dashboard and the detail screen) and the Graphics tab of the detail screen. The picked image loads only while the panel
  is on screen; a loop plays at the file's pace up to 10 frames per second and stops when the tab or screen is left. `o`
  opens the address in the browser, `y` copies it with Textual's clipboard, `[` `]` step a loop and pause it (on a still
  they still step the replay), `space` plays and pauses.
- App: `EyewallApp(inline=...)`, `load_image` (in memory by address and advisory number or satellite time, 48 MB), `floater`
  (a NESDIS product listing, remembered 10 minutes), `color_depth`, `open_graphics`. `run_app` calls `load_inline` before
  Textual starts, which is the only moment the terminal can still be asked, and skips it for `inline = "never"` and
  `--glyphs ascii`.
- Data: `DataSource.image(url)` and `DataSource.satellite_product(storm, product)` on the live source (conditional,
  size-capped) and the replay source (serves the recorded cones from `graphics/`, nothing outside that folder).
- Tests: `tests/test_render_images.py` (limits, frame stepping, the deterministic fallback on small generated images, the
  recorded cone, the lazy-import rule in a subprocess and by source scan), `tests/test_gallery.py`,
  `tests/test_sources_images.py`, `tests/test_ui_graphics.py` (Pilot at 80x24 and 140x45: both entry points, a loop
  stepped, failures, open and copy degrading, inline and fallback choice, no fetch while hidden or unchanged).

**Deviations.**

- The satellite poll still asks for GEOCOLOR only; the air mass and infrared products are listed when the gallery opens
  (`satellite_product`), because each listing is about 1 MB for a long storm.
- `[` and `]` are a gallery binding with a check: on a loop they step frames, on a still they fall through to the replay's
  advisory stepping. In the inline path they step too.
- The fallback uses half blocks for the unicode glyph set, braille when the terminal has no color, and ASCII characters for
  `--glyphs ascii`; the brief allowed half blocks or braille.
- The cone crop uses fixed margins (about 1% border and the bottom 22%, the legend block) measured on the recorded Erin
  cone, applied only to images with the cone's aspect ratio; any other shape only loses a uniform border.
- The real NESDIS listings (checked 31 October 2026) match `docs/data-sources.md`; the doc gained the other product
  directories, the image sizes and the on-demand rule. The NHC landing page was still the quiet-day placeholder, so the link
  patterns for a live storm remain unverified.

**Next session must know.**

- Not viewed by a person: Sixel and Kitty output, and the app in Windows Terminal. The tests drove the gallery through
  Pilot at 80x24 and 140x45 with generated and recorded images, and the inline path with a stand-in widget. Look at the
  gallery in Windows Terminal 1.22 or later, in a terminal without graphics, and with `--glyphs ascii` before release.
- `textual_image.widget` probes the terminal when imported, so it must stay behind `load_inline` and run before the app.
  `tests/test_render_images.py` fails if anything else imports it.
- Gallery tests set `DEBOUNCE_SECONDS` to 0 and wait on state (`loaded`, `wait_until`), never on a timer.
- Python edits on Windows turn LF files into CRLF; check `git ls-files --eol -m` before committing.
