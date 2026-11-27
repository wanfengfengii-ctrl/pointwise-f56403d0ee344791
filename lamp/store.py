import json

from common import database, encode


class LampStore:
    def __init__(self, path):
        self.path = path

    def initialize(self):
        with database(self.path) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS flashes (
                    show TEXT NOT NULL, lamp TEXT NOT NULL,
                    number INTEGER NOT NULL CHECK (number > 0), request_id TEXT NOT NULL,
                    preview_id INTEGER NOT NULL, cue TEXT NOT NULL,
                    PRIMARY KEY (show, lamp, number), UNIQUE (show, lamp, request_id)
                );
                CREATE TABLE IF NOT EXISTS flash_attempts (
                    show TEXT NOT NULL, lamp TEXT NOT NULL, connection TEXT NOT NULL,
                    short INTEGER NOT NULL CHECK (short >= 0), number INTEGER NOT NULL,
                    PRIMARY KEY (show, lamp, connection, short),
                    FOREIGN KEY (show, lamp, number) REFERENCES flashes(show, lamp, number)
                );
            ''')

    def transaction(self):
        return database(self.path, write=True)

    def next_flash_number(self, db, show, lamp):
        last = db.execute('SELECT COALESCE(MAX(number), 0) FROM flashes WHERE show = ? AND lamp = ?',
                          (show, lamp)).fetchone()[0]
        return last + 1

    def insert_flash(self, db, flash):
        db.execute('INSERT INTO flashes(show, lamp, number, request_id, preview_id, cue) '
                   'VALUES (?, ?, ?, ?, ?, ?)',
                   (flash['show'], flash['lamp'], flash['number'], flash['request_id'],
                    flash['preview_id'], encode(flash['cue'])))

    def link_attempt(self, db, show, lamp, connection, short, number):
        db.execute('INSERT INTO flash_attempts VALUES (?, ?, ?, ?, ?)',
                   (show, lamp, connection, short, number))

    def _one(self, statement, parameters, db=None):
        if db is None:
            with database(self.path) as connection:
                return self._one(statement, parameters, connection)
        row = db.execute(statement, parameters).fetchone()
        if row is None:
            return None
        record = dict(row)
        record['cue'] = json.loads(record['cue'])
        return record

    def load_attempt_flash(self, show, lamp, connection, short, db=None):
        return self._one('SELECT flashes.* FROM flash_attempts JOIN flashes USING (show, lamp, number) '
                         'WHERE show = ? AND lamp = ? AND connection = ? AND short = ?',
                         (show, lamp, connection, short), db)

    def load_request_flash(self, db, show, lamp, request_id):
        return self._one('SELECT * FROM flashes WHERE show = ? AND lamp = ? AND request_id = ?',
                         (show, lamp, request_id), db)

    def load_flash(self, show, lamp, number):
        return self._one('SELECT * FROM flashes WHERE show = ? AND lamp = ? AND number = ?',
                         (show, lamp, number))

    def read_head(self, show, lamp):
        with database(self.path) as db:
            return db.execute('SELECT COALESCE(MAX(number), 0) FROM flashes WHERE show = ? AND lamp = ?',
                              (show, lamp)).fetchone()[0]

    def load_prefix(self, show, lamp, head):
        with database(self.path) as db:
            rows = db.execute('SELECT * FROM flashes WHERE show = ? AND lamp = ? AND number <= ? '
                              'ORDER BY number', (show, lamp, head)).fetchall()
        records = []
        for row in rows:
            record = dict(row)
            record['cue'] = json.loads(record['cue'])
            records.append(record)
        return records
