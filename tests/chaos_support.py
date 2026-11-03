"""Support for the chaos tests: a live-style source whose state a test swaps under a running app."""

from __future__ import annotations

from dataclasses import replace

from eyewall.models.advisory import AdvisorySet
from eyewall.models.storm import Classification, CurrentStorms, Storm
from tests.state_support import advisories, make_storm
from tests.ui_support import ScriptedSource

STATES = ("quiet", "one", "multi", "post", "fail")


class MutableSource(ScriptedSource):
    """A `ScriptedSource` whose storms change on demand: no storms, one, three across AL, EP and CP, a post-tropical
    remnant with nothing but a name, or a dead network. Every swap moves the advisory number on, so each is news."""

    def __init__(self) -> None:
        super().__init__()
        self.storm_list: tuple[Storm, ...] = ()
        self.advs: dict[str, AdvisorySet] = {}
        self._advisory_number = 1

    async def storms(self) -> CurrentStorms:
        self._check()
        return CurrentStorms(self.storm_list)

    async def advisory(self, storm: Storm, *, fallback: bool = False) -> AdvisorySet:
        return AdvisorySet() if fallback else self.advs.get(storm.id, AdvisorySet())

    def set_state(self, name: str) -> None:
        assert name in STATES, name
        self.fail = name == "fail"
        if self.fail:
            return
        self._advisory_number += 1
        n = str(self._advisory_number)
        if name == "quiet":
            self.storm_list = ()
        elif name == "one":
            self.storm_list = (make_storm(n, storm_id="al012026", name="Ana"),)
        elif name == "multi":
            self.storm_list = (
                make_storm(n, storm_id="al012026", name="Ana", classification=Classification.HU),
                replace(make_storm(n, storm_id="ep022026", name="Boris"), bin_number="EP2"),
                replace(make_storm(n, storm_id="cp012026", name="Iona", lat=15.0, lon=-155.0), bin_number="CP1"),
            )
        else:  # post: a remnant with no pressure, wind, motion or position
            remnant = make_storm(n, storm_id="al012026", name="Ana", classification=Classification.PC)
            self.storm_list = (
                replace(
                    remnant,
                    pressure_mb=None,
                    intensity_kt=None,
                    movement_dir_deg=None,
                    movement_speed_mph=None,
                    lat=None,
                    lon=None,
                ),
            )
        self.advs = {s.id: advisories(n) for s in self.storm_list}
