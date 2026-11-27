from dataclasses import dataclass
from uuid import uuid4

from common import ApiError, database, integer, text
from dispatch.orders import DispatchOrder


@dataclass(frozen=True)
class DeliveryAttempt:
    show: str
    request_id: str
    connection: str
    short: int


def connection_name(value):
    value = text(value, 'connection')
    if len(value) > 128 or any(not (char.isascii() and (char.isalnum() or char in '._-')) for char in value):
        raise ApiError(400, 'invalid_connection', 'Use 1 to 128 ASCII letters, digits, dots, dashes or underscores')
    return value


class AttemptStore:
    def __init__(self, path, short_pool):
        self.path = path
        self.short_pool = integer(short_pool, 'short_pool', 1)

    def initialize(self):
        with database(self.path) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS attempts (
                    id INTEGER PRIMARY KEY, show TEXT NOT NULL, request_id TEXT NOT NULL,
                    connection TEXT NOT NULL, short INTEGER NOT NULL CHECK (short >= 0),
                    FOREIGN KEY (show, request_id) REFERENCES orders(show, request_id),
                    UNIQUE (connection, short)
                );
                CREATE INDEX IF NOT EXISTS attempts_by_order ON attempts(show, request_id, id);
            ''')

    @staticmethod
    def _attempt(row):
        return DeliveryAttempt(row['show'], row['request_id'], row['connection'], row['short'])

    @staticmethod
    def _find(db, connection, short):
        return db.execute('SELECT * FROM attempts WHERE connection = ? AND short = ?',
                          (connection, short)).fetchone()

    def record_attempt(self, order: DispatchOrder, transport=None):
        with database(self.path, write=True) as db:
            if transport is None:
                previous = db.execute('SELECT * FROM attempts WHERE show = ? AND request_id = ? '
                                      'ORDER BY id LIMIT 1', (order.show, order.request_id)).fetchone()
                if previous is not None:
                    return self._attempt(previous)
                last = db.execute('SELECT COALESCE(MAX(id), 0) FROM attempts').fetchone()[0]
                connection, short = uuid4().hex, last % self.short_pool
            else:
                connection, short = transport
                previous = self._find(db, connection, short)
                if previous is not None:
                    attempt = self._attempt(previous)
                    if (attempt.show, attempt.request_id) != (order.show, order.request_id):
                        raise ApiError(409, 'attempt_conflict', 'This connection and short number belong to another request')
                    return attempt
            db.execute('INSERT INTO attempts(show, request_id, connection, short) VALUES (?, ?, ?, ?)',
                       (order.show, order.request_id, connection, short))
        return DeliveryAttempt(order.show, order.request_id, connection, short)

    def find_attempt(self, connection, short):
        with database(self.path) as db:
            row = self._find(db, connection, short)
        return None if row is None else self._attempt(row)
