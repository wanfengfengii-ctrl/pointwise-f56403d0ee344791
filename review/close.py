from dataclasses import dataclass

from dispatch.orders import OrderStore
from review.archive import BookArchive
from review.reconcile import reconcile_show
from review.snapshot import build_book_snapshot


@dataclass(frozen=True)
class CloseResult:
    pending: tuple[str, ...]
    book: dict | None

    def result(self):
        if self.book is None:
            return {'status': 'pending', 'pending': list(self.pending)}
        return self.book


def close_book(orders: OrderStore, lamps, archive: BookArchive, show):
    reconciliation = reconcile_show(orders, lamps, show)
    if reconciliation.pending:
        return CloseResult(reconciliation.pending, None)
    snapshot = build_book_snapshot(show, reconciliation)
    return CloseResult((), archive.seal_book(snapshot))
