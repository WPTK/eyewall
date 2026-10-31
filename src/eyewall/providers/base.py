"""The provider seam: what the app needs from one agency's storm feeds, and the error parsers raise.

NHC, CPHC and NWS are the only agency in 0.1; JTWC or another agency would implement the same protocol. Parsers are
pure functions over text or bytes and never fetch; a provider object pairs them with a client.
"""

from __future__ import annotations

from typing import Protocol

from eyewall.models.advisory import AdvisorySet
from eyewall.models.forecast import ForecastGis
from eyewall.models.graphics import GraphicLink
from eyewall.models.outlook import OutlookGis, OutlookText
from eyewall.models.storm import CurrentStorms, Storm
from eyewall.models.track import BestTrack


class ParseError(ValueError):
    """A payload that is not the product it claims to be (not JSON, not a zip, no recognisable header).

    Missing and extra fields are not errors: parsers tolerate them. This is for a payload nothing can be made of.
    """


class StormProvider(Protocol):
    """One agency's storm data. Methods return None (or an empty value) when a product does not exist for a storm."""

    name: str

    async def storms(self) -> CurrentStorms: ...

    async def advisory(self, storm: Storm) -> AdvisorySet: ...

    async def forecast_gis(self, storm: Storm) -> ForecastGis | None: ...

    async def track(self, storm: Storm) -> BestTrack | None: ...

    async def outlook_text(self) -> tuple[OutlookText, ...]: ...

    async def outlook_gis(self) -> OutlookGis: ...

    async def graphics(self, storm: Storm) -> tuple[GraphicLink, ...]: ...
