"""Which marks sit in which map cells: the hit map that draw_scene returns.

Pure, with no Textual. A mark is a storm, a buoy or a tide gauge, named by its kind and id. `Hits.at` finds the marks
under a cell, with a tolerance so a one-cell mark can be hit from beside it, and `Hits.step` walks the marks in the
order the keyboard visits them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NamedTuple

Cell = tuple[int, int]
MarkKind = Literal["storm", "buoy", "gauge"]
TOLERANCE = 1  # a click this many cells from a mark still hits it


class Mark(NamedTuple):
    kind: MarkKind
    id: str


@dataclass(frozen=True)
class Hits:
    """`drawn` lists every mark with its cell, topmost first; `order` is the keyboard order."""

    drawn: tuple[tuple[Mark, Cell], ...] = ()
    order: tuple[Mark, ...] = ()

    def at(self, col: int, row: int, tolerance: int = TOLERANCE) -> tuple[Mark, ...]:
        """The marks nearest a cell, topmost first: those in the cell, else the closest ones within the tolerance."""
        best: list[Mark] = []
        reach = tolerance + 1
        for mark, (c, r) in self.drawn:
            distance = max(abs(c - col), abs(r - row))  # in whole cells, diagonals counting one
            if distance > tolerance or mark in best:
                continue
            if distance < reach:
                best, reach = [], distance
            if distance == reach:
                best.append(mark)
        return tuple(best)

    def cell_of(self, mark: Mark) -> Cell | None:
        return next((cell for m, cell in self.drawn if m == mark), None)

    def step(self, current: Mark | None, direction: int) -> Mark | None:
        """The mark after (direction 1) or before (-1) the current one, wrapping. Without a current mark, the first
        going forward and the last going back."""
        if not self.order:
            return None
        if current not in self.order:
            return self.order[0] if direction > 0 else self.order[-1]
        return self.order[(self.order.index(current) + direction) % len(self.order)]


EMPTY_HITS = Hits()
