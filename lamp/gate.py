import threading
import time


class PauseGate:
    """In-memory pause marker gate for one lamp process.

    A marker drains the first-light executions already in flight and then holds
    new executions for the same show until release or the TTL expires.  The wait
    is bounded, so an unreachable duty desk can never block this lamp forever.
    Markers are not persisted: after a lamp restart the desk simply re-arms the
    same mark id, while sealed books remain fixed in the desk database.
    """

    def __init__(self, ttl=5.0):
        if ttl <= 0:
            raise ValueError('pause_ttl must be positive')
        self.ttl = float(ttl)
        self._condition = threading.Condition()
        self._active = 0
        self._holds = {}

    def _held(self, show, now):
        deadline = self._holds.get(show)
        return deadline is not None and deadline > now

    def arm(self, show, mark_id):
        with self._condition:
            now = time.monotonic()
            replay = self._held(show, now)
            if not replay:
                # Drain executions that started before this marker.  An execution
                # entering while no hold is set increments immediately (see enter),
                # so it is counted here and drained too rather than deadlocking us.
                self._condition.wait_for(lambda: self._active == 0, timeout=self.ttl)
            # (Re)arm under the incoming mark id with a fresh deadline.
            self._holds[show] = time.monotonic() + self.ttl
            return replay

    def enter(self, show):
        with self._condition:
            if self._held(show, time.monotonic()):
                # Bounded delay only: never hold an ordinary first light past the TTL.
                self._condition.wait_for(lambda: not self._held(show, time.monotonic()),
                                         timeout=self.ttl)
            self._active += 1

    def leave(self, show):
        with self._condition:
            self._active -= 1
            if self._active == 0:
                self._condition.notify_all()

    def release(self, show, mark_id):
        with self._condition:
            deadline = self._holds.get(show)
            if deadline is not None and deadline > time.monotonic():
                del self._holds[show]
                self._condition.notify_all()
                return True
            return False
