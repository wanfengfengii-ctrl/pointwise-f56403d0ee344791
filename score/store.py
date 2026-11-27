from common import database


class ScoreStore:
    def __init__(self, path):
        self.path = path

    def initialize(self):
        with database(self.path) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS score_revisions (
                    id INTEGER PRIMARY KEY, show TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS score_sections (
                    revision INTEGER NOT NULL REFERENCES score_revisions(id),
                    name TEXT NOT NULL, position INTEGER NOT NULL,
                    PRIMARY KEY (revision, name), UNIQUE (revision, position)
                );
                CREATE TABLE IF NOT EXISTS score_cues (
                    revision INTEGER NOT NULL, cue_id TEXT NOT NULL, section TEXT NOT NULL,
                    voice TEXT NOT NULL, beat TEXT NOT NULL, position INTEGER NOT NULL,
                    text TEXT NOT NULL, PRIMARY KEY (revision, cue_id), UNIQUE (revision, position),
                    FOREIGN KEY (revision, section) REFERENCES score_sections(revision, name)
                );
            ''')

    def insert_revision(self, show, sections, cues):
        with database(self.path, write=True) as db:
            revision = db.execute('INSERT INTO score_revisions(show) VALUES (?)', (show,)).lastrowid
            db.executemany('INSERT INTO score_sections VALUES (?, ?, ?)',
                           ((revision, section.name, section.position) for section in sections))
            # Decimal text keeps the beat exact even above SQLite's integer range.
            db.executemany('INSERT INTO score_cues VALUES (?, ?, ?, ?, ?, ?, ?)',
                           ((revision, cue.cue_id, cue.section, cue.voice, str(cue.beat),
                             cue.position, cue.text) for cue in cues))
        return revision

    def load_revision(self, show, revision):
        with database(self.path) as db:
            header = db.execute('SELECT id FROM score_revisions WHERE id = ? AND show = ?',
                                (revision, show)).fetchone()
            if header is None:
                return None
            sections = db.execute('SELECT name, position FROM score_sections WHERE revision = ? '
                                  'ORDER BY position', (revision,)).fetchall()
            cues = db.execute('SELECT cue_id, section, voice, beat, position, text FROM score_cues '
                              'WHERE revision = ? ORDER BY position', (revision,)).fetchall()
        return sections, cues
