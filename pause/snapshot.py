from dataclasses import asdict, dataclass
from threading import Lock

from lamp.http import LampClient
from plan.order import PlannedCue
from pause.store import PauseStore
from wire import WireError


class CutlineUnavailable(Exception):
    """Raised when a common cross-lamp cutline cannot be evidenced."""


@dataclass(frozen=True)
class PauseEntry:
    request_id: str
    lamp: str
    number: int
    preview_id: int
    cue: PlannedCue


def _head(client: LampClient, show):
    response = client.pause_head(show)
    head = response.get('head')
    if type(head) is not int or head < 0:
        raise CutlineUnavailable('Lamp returned an invalid flash head')
    return head


class PauseService:
    """Coordinates the two-lamp common cutline over HTTP.

    At most one lamp (the first in the sorted roster) is briefly held by a
    pause marker while both heads are read, so the two heads are guaranteed to
    have coexisted at one real instant.  The other lamp keeps serving ordinary
    first lights throughout.  Any unanswered or inconsistent evidence keeps the
    mark pending without changing the original dispatch or settlement state.
    """

    def __init__(self, store: PauseStore, lamps: dict[str, LampClient]):
        self.store = store
        self.lamps = lamps
        self._lock = Lock()

    def mark(self, show, mark_id):
        with self._lock:
            state = self.store.begin_mark(show, mark_id)
            if state == 'sealed':
                return self.store.read_mark(show, mark_id)
            try:
                sealed = self._seal(show, mark_id)
            except (WireError, CutlineUnavailable, KeyError, TypeError, ValueError):
                return {'show': show, 'mark_id': mark_id, 'status': 'pending'}
            return self.store.seal_mark(show, mark_id, sealed)

    def read(self, show, mark_id):
        return self.store.read_mark(show, mark_id)

    def _seal(self, show, mark_id):
        names = sorted(self.lamps)
        held = names[0] if names else None
        held_head = None
        try:
            if held is not None:
                marker = self.lamps[held].pause_marker(show, mark_id)
                held_head = marker.get('head')
                if type(held_head) is not int or held_head < 0:
                    raise CutlineUnavailable('Pause marker returned an invalid head')
            heads = {name: _head(self.lamps[name], show) for name in names}
            if held is not None and heads[held] != held_head:
                # The hold lapsed before both heads were observed: the pair may
                # never have coexisted, so this attempt cannot seal the mark.
                raise CutlineUnavailable('Held lamp moved before the cutline was read')
            entries = []
            for name in names:
                for number in range(1, heads[name] + 1):
                    flash = self.lamps[name].read_flash(show, number)
                    if (flash is None or flash.show != show or flash.lamp != name
                            or flash.number != number):
                        raise CutlineUnavailable('A prefix flash could not be evidenced')
                    entries.append(PauseEntry(flash.request_id, flash.lamp, flash.number,
                                              flash.preview_id, flash.cue))
        finally:
            if held is not None:
                try:
                    self.lamps[held].pause_release(show, mark_id)
                except WireError:
                    # The lamp-side TTL still releases the hold on its own.
                    pass
        entries.sort(key=lambda entry: (entry.lamp, entry.number))
        return {'show': show, 'mark_id': mark_id, 'status': 'sealed',
                'heads': {name: heads[name] for name in names},
                'entries': [asdict(entry) for entry in entries]}
