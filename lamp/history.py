from dataclasses import dataclass

from lamp.store import LampStore
from plan.order import PlannedCue


@dataclass(frozen=True)
class ActualFlash:
    show: str
    lamp: str
    number: int
    request_id: str
    preview_id: int
    cue: PlannedCue

    @classmethod
    def from_record(cls, record):
        return cls(record['show'], record['lamp'], record['number'], record['request_id'],
                   record['preview_id'], PlannedCue.from_record(record['cue']))


def find_attempt_flash(store: LampStore, show, lamp, connection, short, db=None):
    record = store.load_attempt_flash(show, lamp, connection, short, db)
    return None if record is None else ActualFlash.from_record(record)


def read_flash(store: LampStore, show, lamp, number):
    record = store.load_flash(show, lamp, number)
    return None if record is None else ActualFlash.from_record(record)
