import json

from common import ApiError, database, encode


class PauseStore:
    """Persists pause marks and their sealed books in the desk's own database.

    A sealed snapshot is stored verbatim, so re-opening the desk and taking both
    lamps offline still returns the same fixed book for the same mark id.
    """

    def __init__(self, path):
        self.path = path

    def initialize(self):
        with database(self.path) as db:
            db.execute('''
                CREATE TABLE IF NOT EXISTS pause_marks (
                    show TEXT NOT NULL, mark_id TEXT NOT NULL,
                    status TEXT NOT NULL, sealed TEXT,
                    PRIMARY KEY (show, mark_id),
                    CHECK (status IN ('pending', 'sealed')),
                    CHECK ((status = 'sealed') = (sealed IS NOT NULL))
                )
            ''')

    def begin_mark(self, show, mark_id):
        with database(self.path, write=True) as db:
            row = db.execute('SELECT status, sealed FROM pause_marks WHERE show = ? AND mark_id = ?',
                             (show, mark_id)).fetchone()
            if row is None:
                db.execute('INSERT INTO pause_marks(show, mark_id, status) VALUES (?, ?, ?)',
                           (show, mark_id, 'pending'))
                return 'pending'
            return row['status']

    def seal_mark(self, show, mark_id, sealed):
        with database(self.path, write=True) as db:
            row = db.execute('SELECT status, sealed FROM pause_marks WHERE show = ? AND mark_id = ?',
                             (show, mark_id)).fetchone()
            if row is not None and row['status'] == 'sealed':
                return json.loads(row['sealed'])
            db.execute('UPDATE pause_marks SET status = ?, sealed = ? WHERE show = ? AND mark_id = ?',
                       ('sealed', encode(sealed), show, mark_id))
        return sealed

    def read_mark(self, show, mark_id):
        with database(self.path) as db:
            row = db.execute('SELECT status, sealed FROM pause_marks WHERE show = ? AND mark_id = ?',
                             (show, mark_id)).fetchone()
        if row is None:
            raise ApiError(404, 'unknown_pause', 'Unknown pause mark for this show')
        if row['status'] == 'pending':
            return {'show': show, 'mark_id': mark_id, 'status': 'pending'}
        return json.loads(row['sealed'])
