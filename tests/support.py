import json
import sqlite3
import unittest
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread

from dispatch.http import serve_duty
from lamp.http import serve_lamp
from wire import CONNECTION_HEADER, fetch, make_server, query_path


SHOW = 'qinghe'


def sample():
    return json.loads((Path(__file__).resolve().parents[1] / 'sample.json').read_text(encoding='utf-8'))


class RunningServer:
    def __init__(self, server):
        self.server = server
        self.port = server.server_port
        self.thread = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


@dataclass
class HeldDelivery:
    body: dict
    connection: str
    response: dict | None = None

    def forward(self, lamp_port):
        return fetch(lamp_port, 'POST', '/execute', self.body, headers={CONNECTION_HEADER: self.connection})


class LampRelay:
    def __init__(self):
        self.target = None
        self.hold_next = {}
        self.held = {}
        self.executed = []
        self.http = RunningServer(make_server(0, {
            ('POST', '/execute'): self.execute,
            ('GET', '/attempt_result'): self.attempt_result,
            ('GET', '/flash'): self.flash,
        }))

    def execute(self, request):
        body = request.body
        key = body['request_id']
        delivery = HeldDelivery(body, request.headers[CONNECTION_HEADER])
        self.executed.append((key, delivery.connection, body['short']))
        phase = self.hold_next.pop(key, None)
        if phase == 'before':
            self.held[key] = delivery
            return 503, {'error': 'delivery_held'}
        status, response = delivery.forward(self.target)
        if phase == 'after' and status == 200:
            delivery.response = response
            self.held[key] = delivery
            return 503, {'error': 'reply_held'}
        return status, response

    def attempt_result(self, request):
        return fetch(self.target, 'GET', query_path('/attempt_result', **request.query))

    def flash(self, request):
        return fetch(self.target, 'GET', query_path('/flash', **request.query))


class Rehearsal:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.duty_db = self.directory / 'duty.sqlite3'
        self.relays = {}
        self.lamps = {}
        self.duty = None

    def __enter__(self):
        try:
            for lamp in ('alpha', 'beta'):
                self.relays[lamp] = LampRelay()
            self._start_duty(0)
            for lamp in self.relays:
                self._start_lamp(lamp)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exception):
        if self.duty is not None:
            self.duty.close()
        for lamp in self.lamps.values():
            lamp.close()
        for relay in self.relays.values():
            relay.http.close()

    def _start_duty(self, port):
        ports = {lamp: relay.http.port for lamp, relay in self.relays.items()}
        self.duty = RunningServer(serve_duty(self.duty_db, SHOW, ports, port, short_pool=2))

    def _start_lamp(self, lamp):
        path = self.directory / (lamp + '.sqlite3')
        server = RunningServer(serve_lamp(path, SHOW, lamp, self.duty.port))
        self.lamps[lamp] = server
        self.relays[lamp].target = server.port

    def restart(self):
        port = self.duty.port
        self.duty.close()
        self.duty = None
        self._start_duty(port)
        for lamp in self.relays:
            self.lamps.pop(lamp).close()
            self._start_lamp(lamp)

    def post(self, path, body):
        return fetch(self.duty.port, 'POST', path, body)

    def get(self, path, **query):
        return fetch(self.duty.port, 'GET', query_path(path, show=SHOW, **query))

    def prepare(self, score=None):
        example = sample()
        status, revision = self.post('/score_write', example['score'] if score is None else score)
        if status != 201:
            raise AssertionError((status, revision))
        status, preview = self.post('/preview', {'show': SHOW, 'revision': revision['revision'],
                                                'section': example['section'], 'assignments': example['assignments']})
        if status != 201:
            raise AssertionError((status, preview))
        return preview

    def send(self, preview, request_id, cue_id, target=None, transport=None):
        planned = next((cue for cue in preview['cues'] if cue['source']['cue_id'] == cue_id), None)
        if target is None:
            target = planned['lamp']
        body = {'show': SHOW, 'request_id': request_id, 'preview_id': preview['preview_id'],
                'cue_id': cue_id, 'target': target}
        if transport is not None:
            body['transport'] = {'connection': transport[0], 'short': transport[1]}
        return self.post('/send', body)

    def hold(self, lamp, request_id, phase):
        if phase not in ('before', 'after'):
            raise ValueError(f'Unknown hold phase {phase}')
        self.relays[lamp].hold_next[request_id] = phase

    def execute_held(self, lamp, request_id, *, target=None):
        delivery = self.relays[lamp].held[request_id]
        receiver = lamp if target is None else target
        status, response = delivery.forward(self.lamps[receiver].port)
        if status == 200:
            delivery.response = response
        return status, response

    def release_report(self, lamp, request_id):
        delivery = self.relays[lamp].held[request_id]
        if delivery.response is None:
            raise AssertionError('No real lamp response has been captured')
        return self.report(delivery.connection, delivery.response)

    def report(self, connection, response):
        headers = {} if connection is None else {CONNECTION_HEADER: connection}
        return fetch(self.duty.port, 'POST', '/report', response, headers=headers)

    def flash(self, lamp, number):
        return fetch(self.lamps[lamp].port, 'GET', query_path('/flash', show=SHOW, number=number))

    def attempt_result(self, lamp, connection, short):
        path = query_path('/attempt_result', show=SHOW, connection=connection, short=short)
        return fetch(self.lamps[lamp].port, 'GET', path)

    def close_book(self):
        return self.post('/close_book', {'show': SHOW})

    def duty_counts(self):
        with closing(sqlite3.connect(self.duty_db)) as db:
            return db.execute('SELECT (SELECT COUNT(*) FROM score_revisions), '
                              '(SELECT COUNT(*) FROM score_cues), (SELECT COUNT(*) FROM previews), '
                              '(SELECT COUNT(*) FROM books)').fetchone()


class RehearsalTest(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory(prefix='qinghe-test-'))
        self.env = self.enterContext(Rehearsal(directory))
