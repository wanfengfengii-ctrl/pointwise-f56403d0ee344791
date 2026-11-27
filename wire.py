import json
from dataclasses import dataclass
from email.message import Message
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

from common import ApiError, encode


CONNECTION_HEADER = 'X-Delivery-Connection'
MAX_BODY = 2 * 1024 * 1024


class WireError(Exception):
    pass


@dataclass(frozen=True)
class JsonRequest:
    body: object
    query: dict[str, str]
    headers: Message


def _invalid_constant(value):
    raise ValueError(f'Invalid JSON constant: {value}')


def _decode(payload):
    return json.loads(payload.decode('utf-8'), parse_constant=_invalid_constant)


def query_path(route, **parameters):
    return route + '?' + urlencode(parameters)


def fetch(port, method, path, body=None, *, headers=None):
    if body is not None:
        headers = {'Content-Type': 'application/json', **(headers or {})}
    connection = HTTPConnection('127.0.0.1', port, timeout=5)
    try:
        payload = None if body is None else encode(body).encode('ascii')
        connection.request(method, path, body=payload, headers=headers or {})
        response = connection.getresponse()
        return response.status, _decode(response.read())
    except (OSError, HTTPException, ValueError, RecursionError) as exc:
        raise WireError(f'{method} {path.split("?", 1)[0]} did not return a readable response') from exc
    finally:
        connection.close()


def make_server(port, routes):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def _body(self):
            size = self.headers.get('Content-Length', '')
            if not size.isascii() or not size.isdecimal() or len(size) > 10:
                raise ApiError(400, 'invalid_body', 'A JSON body with a valid Content-Length is required')
            length = int(size)
            if not 0 < length <= MAX_BODY:
                raise ApiError(400, 'invalid_body', 'The JSON body must contain 1 to 2097152 bytes')
            payload = self.rfile.read(length)
            if len(payload) != length:
                raise ApiError(400, 'invalid_body', 'The JSON body is incomplete')
            try:
                return _decode(payload)
            except (ValueError, RecursionError) as exc:
                raise ApiError(400, 'invalid_json', 'The request body is not valid JSON') from exc

        def _handle(self):
            try:
                try:
                    target = urlsplit(self.path)
                    parameters = parse_qs(target.query, keep_blank_values=True, strict_parsing=True,
                                          encoding='utf-8', errors='strict')
                except ValueError as exc:
                    raise ApiError(400, 'invalid_query', 'Malformed query string') from exc
                if any(len(values) != 1 for values in parameters.values()):
                    raise ApiError(400, 'invalid_query', 'Each query parameter must occur once')
                route = routes.get((self.command, target.path))
                if route is None:
                    raise ApiError(404, 'unknown_route', 'Unknown HTTP endpoint')
                request = JsonRequest(self._body() if self.command == 'POST' else None,
                                      {key: values[0] for key, values in parameters.items()}, self.headers)
                status, result = route(request)
            except ApiError as exc:
                status, result = exc.status, {'error': exc.code, 'message': str(exc)}
            payload = encode(result).encode('ascii')
            try:
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                # A client losing its reply does not roll back committed business state.
                return

        do_GET = _handle
        do_POST = _handle

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)
