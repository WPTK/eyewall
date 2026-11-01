"""The rest of the panel beside the map: what NHC is watching, your stations, the stations near the storm and the replay
offer. Each is a few plain sentences from `ui.words` or the station helpers, built as whole blocks.

The same sentences, without headings, make up the strip under the map on a small terminal when nothing is active.
"""

from __future__ import annotations

from eyewall.sources import protocol
from eyewall.ui import stations as st
from eyewall.ui.widgets.side_panel import DO, Block, View, heading, link, wrapped
from eyewall.ui.words import outlook as outlook_words

SHOW_BUOYS = f"{DO}:buoys"
SHOW_OUTLOOK = f"{DO}:outlook"
AREAS_NOUN = ("outlook note", "outlook notes")
START_REPLAY = f"{DO}:app.start_replay"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def outlook_text(view: View) -> list[str]:
    """NHC's outlook in plain sentences: one for a single area, a lead and a line each for several, the summary as
    issued for none. Empty while a storm is active and no area is being watched."""
    store = view.store
    if store.outlook is None:
        return ["Outlook data unavailable."] if protocol.OUTLOOK in view.failed else []
    if not view.states or outlook_words.area_count(store.outlook, view.basins):
        return [w.text for w in outlook_words.outlook_sentences(store.outlook, view.basins)]
    return []


def stations_text(view: View) -> str | None:
    """`4 buoys and 1 tide gauge. Highest wind 18 mph. 1 buoy not reporting.`, or None when none are followed."""
    store = view.store
    buoys, gauges = st.watchlist_buoys(store), st.watchlist_gauges(store)
    if not buoys and not gauges:
        return None
    parts = [_plural(len(buoys), "buoy")] if buoys else []
    if gauges:
        parts.append(_plural(len(gauges), "tide gauge"))
    text = " and ".join(parts) + "."
    if protocol.BUOYS in view.failed:
        return text + " Buoy data unavailable."
    winds: list[float] = []
    silent = 0
    for entry in buoys:
        state = st.buoy_state(store, entry.id, view.now)
        if state in ("silent", "dark"):
            silent += 1
        elif state == "ok":
            wind = st.wind_kt(st.newest_observation(store, entry.id))
            if wind is not None:
                winds.append(wind)
    if winds:
        text += f" Highest wind {view.preset.fmt_wind(max(winds))}."
    if silent:
        text += f" {_plural(silent, 'buoy')} not reporting."
    return text


def areas_block(view: View, width: int, *, priority: int) -> list[Block]:
    sentences = outlook_text(view)
    if not sentences:
        return []
    title = "Also watching" if view.states else "Areas NHC is watching"
    out = [heading(title, "areas")]
    for text in sentences:  # one block per area, so a short column keeps the first and counts the rest
        lines = wrapped(text, width, prefix="  ", action=SHOW_OUTLOOK)
        out.append(Block(tuple(lines), priority, group="areas", more=SHOW_OUTLOOK, section="areas", noun=AREAS_NOUN))
    return out


def stations_block(view: View, width: int, *, priority: int) -> list[Block]:
    text = stations_text(view)
    if text is None:
        return []
    lines = (
        *wrapped(text, width, prefix="  ", action=SHOW_BUOYS),
        link(view, "open the list", SHOW_BUOYS, key="b"),
    )
    return [heading("Your stations", "stations"), Block(lines, priority, section="stations")]


def near_block(view: View, width: int, *, priority: int) -> list[Block]:
    state = view.chosen
    if state is None:
        return []
    buoys = len(view.store.nearby_buoys(state.storm.id, view.now))
    gauges = len(view.store.nearby_tides(state.storm.id, view.now))
    if not buoys and not gauges:
        return []
    parts = ([_plural(buoys, "buoy")] if buoys else []) + ([_plural(gauges, "tide gauge")] if gauges else [])
    name = state.storm.name.title() if state.storm.name else state.storm.id.upper()
    text = f"{' and '.join(parts)} near {name}."
    lines = (
        *wrapped(text, width, prefix="  ", action=SHOW_BUOYS),
        link(view, "open the list", SHOW_BUOYS, key="b"),
    )
    return [heading(f"Near {name}", "near"), Block(lines, priority, section="near")]


def replay_block(view: View, width: int, *, priority: int) -> list[Block]:
    if view.replay_offer is None:
        return []
    text = f"Replay {view.replay_offer} on these same screens."
    lines = (
        *wrapped(text, width, prefix="  ", action=START_REPLAY),
        link(view, "start the replay", START_REPLAY, key="R"),
    )
    return [heading("See it with a storm", "replay"), Block(lines, priority, section="replay")]


def quiet_strip(view: View, width: int) -> list[Block]:
    """The strip when nothing is active: the outlook (one block per sentence, then `+N more >` or `N outlook notes >`
    that opens the full text), the replay offer, then your stations. It is never left empty."""
    out: list[Block] = []
    for text in outlook_text(view):
        lines = wrapped(text, width, action=SHOW_OUTLOOK)
        out.append(Block(tuple(lines), 0, group="outlook", more=SHOW_OUTLOOK, noun=AREAS_NOUN))
    if view.replay_offer is not None:
        offer = wrapped(f"R  replay {view.replay_offer} {view.g.crumb}", width, action=START_REPLAY)
        out.append(Block(tuple(offer), 1))
    stations = stations_text(view)
    if stations is not None:
        out.append(Block(tuple(wrapped(f"Your stations: {stations}", width, action=SHOW_BUOYS)), 2))
    return out


__all__ = ["areas_block", "near_block", "outlook_text", "quiet_strip", "replay_block", "stations_block"]
