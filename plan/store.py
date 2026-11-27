import json

from common import database, encode


class PreviewStore:
    def __init__(self, path):
        self.path = path

    def initialize(self):
        with database(self.path) as db:
            db.execute('''
                CREATE TABLE IF NOT EXISTS previews (
                    id INTEGER PRIMARY KEY, show TEXT NOT NULL,
                    revision INTEGER NOT NULL REFERENCES score_revisions(id),
                    section TEXT NOT NULL, assignments TEXT NOT NULL, cues TEXT NOT NULL
                )
            ''')

    def insert_preview(self, show, revision, section, assignments, cues):
        with database(self.path, write=True) as db:
            return db.execute('INSERT INTO previews(show, revision, section, assignments, cues) '
                              'VALUES (?, ?, ?, ?, ?)',
                              (show, revision, section, encode(assignments), encode(cues))).lastrowid

    def load_preview(self, show, preview_id):
        with database(self.path) as db:
            row = db.execute('SELECT revision, section, assignments, cues FROM previews '
                             'WHERE show = ? AND id = ?', (show, preview_id)).fetchone()
        if row is None:
            return None
        return row['revision'], row['section'], json.loads(row['assignments']), json.loads(row['cues'])
