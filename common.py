import json
import sqlite3
from contextlib import contextmanager


class ApiError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code


def fields(value, required, optional=()):
    if not isinstance(value, dict):
        raise ApiError(400, 'invalid_fields', 'Expected a JSON object')
    missing = set(required) - value.keys()
    extra = value.keys() - set(required) - set(optional)
    if missing or extra:
        raise ApiError(400, 'invalid_fields',
                       f'Missing fields {sorted(missing)}, unexpected fields {sorted(extra)}')
    return value


def text(value, label):
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise ApiError(400, 'invalid_text', f'{label} must be a nonempty string without NUL')
    try:
        value.encode('utf-8')
    except UnicodeError as exc:
        raise ApiError(400, 'invalid_text', f'{label} must be valid Unicode') from exc
    return value


def integer(value, label, minimum=0, maximum=2**63 - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ApiError(400, 'invalid_integer', f'{label} must be an integer from {minimum} to {maximum}')
    return value


def query_integer(value, label, minimum=0):
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal() or len(value) > 19:
        raise ApiError(400, 'invalid_integer', f'{label} must be a decimal integer')
    return integer(int(value), label, minimum)


def require_show(value, show):
    if value != show:
        raise ApiError(404, 'unknown_show', 'This service does not serve the requested show')


def encode(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False)


@contextmanager
def database(path, *, write=False):
    connection = sqlite3.connect(path, timeout=5)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        with connection:
            if write:
                connection.execute('BEGIN IMMEDIATE')
            yield connection
    finally:
        connection.close()
