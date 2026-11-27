import json
from dataclasses import asdict

from common import ApiError, database, encode
from review.snapshot import BookSnapshot


class BookArchive:
    def __init__(self, path):
        self.path = path

    def initialize(self):
        with database(self.path) as db:
            db.execute('''
                CREATE TABLE IF NOT EXISTS books (
                    id INTEGER PRIMARY KEY, show TEXT NOT NULL, snapshot TEXT NOT NULL
                )
            ''')

    def seal_book(self, snapshot: BookSnapshot):
        record = asdict(snapshot)
        with database(self.path, write=True) as db:
            book_id = db.execute('INSERT INTO books(show, snapshot) VALUES (?, ?)',
                                 (snapshot.show, encode(record))).lastrowid
        return {'status': 'closed', 'book_id': book_id, **record}

    def read_book(self, show, book_id):
        with database(self.path) as db:
            row = db.execute('SELECT snapshot FROM books WHERE show = ? AND id = ?', (show, book_id)).fetchone()
        if row is None:
            raise ApiError(404, 'unknown_book', 'Unknown closed book for this show')
        return {'status': 'closed', 'book_id': book_id, **json.loads(row['snapshot'])}
