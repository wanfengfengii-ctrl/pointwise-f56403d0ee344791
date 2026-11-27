from dataclasses import dataclass

from plan.order import PlannedCue
from review.reconcile import Reconciliation


@dataclass(frozen=True)
class BookEntry:
    request_id: str
    lamp: str
    number: int
    preview_id: int
    cue: PlannedCue


@dataclass(frozen=True)
class BookSnapshot:
    show: str
    entries: tuple[BookEntry, ...]


def build_book_snapshot(show, reconciliation: Reconciliation):
    if reconciliation.pending:
        raise ValueError('A snapshot requires all requested flashes to be verified')
    ordered = sorted(reconciliation.verified, key=lambda flash: (flash.lamp, flash.number))
    return BookSnapshot(show, tuple(BookEntry(flash.request_id, flash.lamp, flash.number,
                                              flash.preview_id, flash.cue) for flash in ordered))
