import argparse
from contextlib import closing
from dataclasses import asdict

from common import ApiError, fields, integer, query_integer, require_show, text
from dispatch.attempts import connection_name
from lamp.gate import PauseGate
from lamp.history import ActualFlash, find_attempt_flash, read_flash
from lamp.intake import execute_cue
from lamp.store import LampStore
from wire import CONNECTION_HEADER, WireError, fetch, make_server, query_path


class LampClient:
    def __init__(self, port):
        self.port = port

    def execute(self, fact, connection, short):
        status, report = fetch(self.port, 'POST', '/execute', {**fact, 'short': short},
                               headers={CONNECTION_HEADER: connection})
        if status != 200:
            raise WireError(f'Lamp did not confirm delivery, HTTP {status}')
        return report

    def _read(self, path):
        status, response = fetch(self.port, 'GET', path)
        if status == 404:
            return None
        if status != 200:
            raise WireError(f'Lamp history read failed, HTTP {status}')
        try:
            return ActualFlash.from_record(response)
        except (KeyError, TypeError) as exc:
            raise WireError('Lamp history returned an invalid record') from exc

    def read_attempt_result(self, show, connection, short):
        return self._read(query_path('/attempt_result', show=show, connection=connection, short=short))

    def read_flash(self, show, number):
        return self._read(query_path('/flash', show=show, number=number))

    def pause_marker(self, show, mark_id):
        status, response = fetch(self.port, 'POST', '/pause_marker',
                                 {'show': show, 'mark_id': mark_id})
        if status != 200:
            raise WireError(f'Lamp pause marker failed, HTTP {status}')
        return response

    def pause_head(self, show):
        status, response = fetch(self.port, 'GET', query_path('/pause_head', show=show))
        if status != 200:
            raise WireError(f'Lamp pause head read failed, HTTP {status}')
        return response

    def pause_release(self, show, mark_id):
        status, response = fetch(self.port, 'POST', '/pause_release',
                                 {'show': show, 'mark_id': mark_id})
        if status != 200:
            raise WireError(f'Lamp pause release failed, HTTP {status}')
        return response


def _read_fact(duty_port, show, connection, short):
    route = query_path('/dispatch_fact', show=show, connection=connection, short=short)
    try:
        status, fact = fetch(duty_port, 'GET', route)
    except WireError as exc:
        raise ApiError(503, 'dispatch_unavailable', 'Unable to read accepted dispatch facts') from exc
    if status == 404:
        return None
    if status != 200:
        raise ApiError(503, 'dispatch_unavailable', 'Unable to read accepted dispatch facts')
    return fact


def handle_execute(store, show, lamp, duty_port, gate, request):
    body = fields(request.body, ('show', 'request_id', 'preview_id', 'cue', 'short'))
    require_show(body['show'], show)
    connections = request.headers.get_all(CONNECTION_HEADER) or []
    if len(connections) != 1:
        raise ApiError(400, 'invalid_connection', 'One delivery connection header is required')
    connection = connection_name(connections[0])
    short = integer(body['short'], 'short')
    fact = _read_fact(duty_port, show, connection, short)
    # Only a pause marker may briefly wait here; the gate TTL bounds the delay.
    gate.enter(show)
    try:
        execute_cue(store, show, lamp, body, connection, fact)
    finally:
        gate.leave(show)
    return 200, {'short': short}


def handle_pause_marker(store, gate, show, lamp, request):
    body = fields(request.body, ('show', 'mark_id'))
    require_show(body['show'], show)
    mark_id = text(body['mark_id'], 'mark_id')
    replay = gate.arm(show, mark_id)
    return 200, {'show': show, 'mark_id': mark_id, 'replay': bool(replay),
                 'lamp': lamp, 'head': store.read_head(show, lamp)}


def handle_pause_head(store, show, lamp, query):
    fields(query, ('show',))
    require_show(query['show'], show)
    return 200, {'show': show, 'lamp': lamp, 'head': store.read_head(show, lamp)}


def handle_pause_release(gate, show, request):
    body = fields(request.body, ('show', 'mark_id'))
    require_show(body['show'], show)
    mark_id = text(body['mark_id'], 'mark_id')
    released = gate.release(show, mark_id)
    return 200, {'show': show, 'mark_id': mark_id, 'released': released}


def _flash_response(flash):
    if flash is None:
        raise ApiError(404, 'unknown_flash', 'No committed flash matches this lookup')
    return 200, asdict(flash)


def _handle_attempt_result(store, show, lamp, query):
    fields(query, ('show', 'connection', 'short'))
    require_show(query['show'], show)
    return _flash_response(find_attempt_flash(store, show, lamp, connection_name(query['connection']),
                                              query_integer(query['short'], 'short')))


def _handle_flash(store, show, lamp, query):
    fields(query, ('show', 'number'))
    require_show(query['show'], show)
    return _flash_response(read_flash(store, show, lamp, query_integer(query['number'], 'number', 1)))


def serve_lamp(path, show, lamp, duty_port, port=0, pause_ttl=5.0):
    text(show, 'show')
    text(lamp, 'lamp')
    integer(duty_port, 'duty port', 1, 65535)
    store = LampStore(path)
    store.initialize()
    gate = PauseGate(pause_ttl)
    routes = {
        ('POST', '/execute'): lambda req: handle_execute(store, show, lamp, duty_port, gate, req),
        ('GET', '/attempt_result'): lambda req: _handle_attempt_result(store, show, lamp, req.query),
        ('GET', '/flash'): lambda req: _handle_flash(store, show, lamp, req.query),
        ('POST', '/pause_marker'): lambda req: handle_pause_marker(store, gate, show, lamp, req),
        ('GET', '/pause_head'): lambda req: handle_pause_head(store, show, lamp, req.query),
        ('POST', '/pause_release'): lambda req: handle_pause_release(gate, show, req),
    }
    return make_server(port, routes)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Serve a rehearsal lamp on loopback')
    parser.add_argument('--db', required=True)
    parser.add_argument('--show', required=True)
    parser.add_argument('--lamp', required=True)
    parser.add_argument('--duty-port', type=int, required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--pause-ttl', type=float, default=5.0)
    args = parser.parse_args(argv)
    try:
        integer(args.port, 'port', 1, 65535)
        server = serve_lamp(args.db, args.show, args.lamp, args.port, args.pause_ttl)
    except ApiError as exc:
        parser.error(str(exc))
    with closing(server):
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return 0
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
