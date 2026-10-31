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

(to be filled in by the session)
