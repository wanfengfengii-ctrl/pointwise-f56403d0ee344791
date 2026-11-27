import json
from tempfile import TemporaryDirectory
from threading import Event, Lock

from tests.support import LampRelay, Rehearsal, RunningServer, SHOW
from wire import WireError, fetch, make_server, query_path


class ExchangeGate:
    def __init__(self, method, path, *, after=False, reject=False):
        self.method = method
        self.path = path
        self.after = after
        self.reject = reject
        self.reached = Event()
        self.resume = Event()
        self._lock = Lock()
        self._armed = True

    def __call__(self, method, path, request, forward):
        with self._lock:
            selected = self._armed and (method, path) == (self.method, self.path)
            if selected:
                self._armed = False
        if not selected:
            return forward()
        result = forward() if self.after else None
        self.reached.set()
        if not self.resume.wait(3) or self.reject:
            return 503, {"error": "fixture_exchange_held"}
        return result if self.after else forward()


class RelayRoutes:
    def __init__(self, relay):
        self.relay = relay

    def get(self, key):
        method, path = key
        return lambda request: self.relay.exchange(method, path, request)


class PauseLampRelay(LampRelay):
    def __init__(self):
        self.target = None
        self.hold_next = {}
        self.held = {}
        self.executed = []
        self.gate = None
        self.http = RunningServer(make_server(0, RelayRoutes(self)))

    def exchange(self, method, path, request):
        def forward():
            if self.target is None:
                return 503, {"error": "fixture_lamp_unavailable"}
            try:
                if (method, path) == ("POST", "/execute"):
                    return self.execute(request)
                target = query_path(path, **request.query) if request.query else path
                headers = {key: value for key, value in request.headers.items()
                           if key.lower() not in {"host", "connection", "content-length", "transfer-encoding"}}
                return fetch(self.target, method, target, request.body, headers=headers)
            except WireError:
                return 503, {"error": "fixture_lamp_unavailable"}

        gate = self.gate
        return forward() if gate is None else gate(method, path, request, forward)


class PauseRehearsal(Rehearsal):
    def __enter__(self):
        try:
            for lamp in ("alpha", "beta"):
                self.relays[lamp] = PauseLampRelay()
            self._start_duty(0)
            for lamp in self.relays:
                self._start_lamp(lamp)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def stop_lamp(self, lamp):
        self.relays[lamp].target = None
        self.lamps.pop(lamp).close()

    def restart_duty(self):
        port = self.duty.port
        self.duty.close()
        self.duty = None
        self._start_duty(port)


def lamp_head(env, lamp):
    number = 1
    while True:
        status, record = env.flash(lamp, number)
        if status == 404:
            return number - 1
        if status != 200 or record["number"] != number:
            raise AssertionError((lamp, number, status, record))
        number += 1


def baseline_scenario(env):
    plan = env.prepare()
    status, first = env.send(plan, "U", "A")
    assert (status, first["flash_number"]) == (200, 1)

    def heads():
        return [lamp_head(env, lamp) for lamp in ("alpha", "beta")]

    first_read = heads()
    env.hold("alpha", "X", "after")
    status, x = env.send(plan, "X", "C")
    assert (status, x["status"]) == (200, "pending")
    second_read = heads()
    status, v = env.send(plan, "V", "B")
    assert (status, v["flash_number"]) == (200, 1)
    third_read = heads()
    observed = [first_read, second_read, third_read]
    mixed = [first_read[0], third_read[1]]
    assert observed == [[1, 0], [2, 0], [2, 1]] and mixed not in observed
    status, x_flash = env.flash("alpha", 2)
    cue = next(cue for cue in plan["cues"] if cue["source"]["cue_id"] == "C")
    assert (status, x_flash["request_id"], x_flash["cue"]) == (200, "X", cue)
    assert env.get("/lookup", request_id="X")[1]["status"] == "pending"
    status, book = env.close_book()
    assert (status, book) == (200, {"status": "pending", "pending": ["X"]})
    return {"show": SHOW, "observed_heads_alpha_beta": observed, "mixed_heads_alpha_beta": mixed,
            "actual_x": x_flash, "old_book": book}


def main():
    with TemporaryDirectory(prefix="qinghe-pause-") as directory, PauseRehearsal(directory) as env:
        result = baseline_scenario(env)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
