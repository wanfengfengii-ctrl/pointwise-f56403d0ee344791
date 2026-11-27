import argparse
from contextlib import closing
from dataclasses import asdict

from common import ApiError, fields, integer, query_integer, require_show, text
from dispatch.attempts import connection_name
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


def handle_execute(store, show, lamp, duty_port, request):
    body = fields(request.body, ('show', 'request_id', 'preview_id', 'cue', 'short'))
    require_show(body['show'], show)
    connections = request.headers.get_all(CONNECTION_HEADER) or []
    if len(connections) != 1:
        raise ApiError(400, 'invalid_connection', 'One delivery connection header is required')
    connection = connection_name(connections[0])
    short = integer(body['short'], 'short')
    fact = _read_fact(duty_port, show, connection, short)
    execute_cue(store, show, lamp, body, connection, fact)
    return 200, {'short': short}


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


def serve_lamp(path, show, lamp, duty_port, port=0):
    text(show, 'show')
    text(lamp, 'lamp')
    integer(duty_port, 'duty port', 1, 65535)
    store = LampStore(path)
    store.initialize()
    routes = {
        ('POST', '/execute'): lambda req: handle_execute(store, show, lamp, duty_port, req),
        ('GET', '/attempt_result'): lambda req: _handle_attempt_result(store, show, lamp, req.query),
        ('GET', '/flash'): lambda req: _handle_flash(store, show, lamp, req.query),
    }
    return make_server(port, routes)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Serve a rehearsal lamp on loopback')
    parser.add_argument('--db', required=True)
    parser.add_argument('--show', required=True)
    parser.add_argument('--lamp', required=True)
    parser.add_argument('--duty-port', type=int, required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args(argv)
    try:
        integer(args.port, 'port', 1, 65535)
        server = serve_lamp(args.db, args.show, args.lamp, args.duty_port, args.port)
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
