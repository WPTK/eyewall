
- Words: the outlook text-fallback sentences (`ui/words/outlook.py`) use generic labels and can count a central Pacific area twice; tidy when the outlook is wired into the UI.
- Words: the disabled-basin path in the summary and outlook sentences is only lightly covered; add fixtures with one basin disabled.
- Words: the surge sentence (`ui/words/storm.py`, `warning_sentences`) is softer than NHC's own storm surge wording; align it with the advisory text.
- Words: the glossary meaning is quoted by splitting on the first sentence, which can cut a meaning that has an abbreviation in it; quote the whole paragraph instead.
- Places: NHC reference points (the "about" places in the advisory, such as Bermuda or Cape Hatteras) are not placed on the map yet. They need the advisory parsed into a bearing and distance, placed with `geo.destination`, and passed through the adapter in `ui/adapt.py`, which belongs to the click and hit-testing work.
- Places: the map key under the map does not mention place names or the scale bar; add them when the key is rebuilt with the new main screen.
- Places: the PyInstaller binary size was not re-measured; `places.bin` adds 69,138 bytes (about 50 KB compressed), 1.6% of the 4.3 MB of map data.
