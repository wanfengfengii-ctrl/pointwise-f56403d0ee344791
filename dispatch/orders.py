import json
from dataclasses import asdict, dataclass

from common import ApiError, database, encode
from plan.order import PlannedCue
from plan.preview import require_planned_cue


@dataclass(frozen=True)
class DispatchOrder:
    show: str
    request_id: str
    preview_id: int
    cue: PlannedCue
    actual_lamp: str | None = None
    flash_number: int | None = None

    def fact(self):
        return {'show': self.show, 'request_id': self.request_id,
                'preview_id': self.preview_id, 'cue': asdict(self.cue)}

    def result(self):
        if self.flash_number is None:
            return {**self.fact(), 'status': 'pending'}
        return {**self.fact(), 'status': 'lit',
                'actual_lamp': self.actual_lamp, 'flash_number': self.flash_number}


class OrderStore:
    def __init__(self, path, previews):
        self.path = path
        self.previews = previews

    def initialize(self):
        with database(self.path) as db:
            db.execute('''
                CREATE TABLE IF NOT EXISTS orders (
                    show TEXT NOT NULL, request_id TEXT NOT NULL,
                    preview_id INTEGER NOT NULL REFERENCES previews(id), cue TEXT NOT NULL,
                    actual_lamp TEXT, flash_number INTEGER,
                    PRIMARY KEY (show, request_id),
                    CHECK ((actual_lamp IS NULL) = (flash_number IS NULL)),
                    CHECK (flash_number IS NULL OR flash_number > 0)
                )
            ''')

    @staticmethod
    def _order(row):
        return DispatchOrder(row['show'], row['request_id'], row['preview_id'],
                             PlannedCue.from_record(json.loads(row['cue'])),
                             row['actual_lamp'], row['flash_number'])

    @staticmethod
    def _find(db, show, request_id):
        return db.execute('SELECT * FROM orders WHERE show = ? AND request_id = ?',
                          (show, request_id)).fetchone()

    def accept_order(self, show, request_id, preview_id, cue_id, target):
        with database(self.path, write=True) as db:
            previous = self._find(db, show, request_id)
            if previous is not None:
                order = self._order(previous)
                if (order.preview_id, order.cue.source.cue_id, order.cue.lamp) != (preview_id, cue_id, target):
                    raise ApiError(409, 'request_conflict', 'This request number already fixes different parameters')
                return order
            cue = require_planned_cue(self.previews, show, preview_id, cue_id)
            if cue.lamp != target:
                raise ApiError(409, 'wrong_target', 'Target differs from the frozen cue')
            db.execute('INSERT INTO orders(show, request_id, preview_id, cue) VALUES (?, ?, ?, ?)',
                       (show, request_id, preview_id, encode(asdict(cue))))
        return DispatchOrder(show, request_id, preview_id, cue)

    def get_order(self, show, request_id):
        with database(self.path) as db:
            row = self._find(db, show, request_id)
        if row is None:
            raise ApiError(404, 'unknown_request', 'Unknown dispatch request for this show')
        return self._order(row)

    def list_show_orders(self, show):
        with database(self.path) as db:
            rows = db.execute('SELECT * FROM orders WHERE show = ? ORDER BY request_id', (show,)).fetchall()
        return tuple(self._order(row) for row in rows)

    def mark_lit(self, show, request_id, lamp, number):
        with database(self.path, write=True) as db:
            db.execute('UPDATE orders SET actual_lamp = ?, flash_number = ? '
                       'WHERE show = ? AND request_id = ? AND flash_number IS NULL',
                       (lamp, number, show, request_id))
            row = self._find(db, show, request_id)
            if row is None:
                raise ApiError(404, 'unknown_request', 'Unknown dispatch request for this show')
            return self._order(row)
