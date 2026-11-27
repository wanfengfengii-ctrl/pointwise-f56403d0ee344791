import argparse
from contextlib import closing

from common import ApiError, fields, integer, query_integer, require_show, text
from dispatch.attempts import AttemptStore, connection_name
from dispatch.delivery import deliver_order, handle_short_report
from dispatch.orders import OrderStore
from lamp.http import LampClient
from plan.http import handle_preview, handle_read_preview
from plan.store import PreviewStore
from review.archive import BookArchive
from review.http import handle_close_book, handle_read_book
from score.http import handle_read_revision, handle_score_write
from score.store import ScoreStore
from wire import CONNECTION_HEADER, make_server


def handle_send(orders, attempts, lamps, show, body):
    fields(body, ('show', 'request_id', 'preview_id', 'cue_id', 'target'), ('transport',))
    require_show(body['show'], show)
    request_id = text(body['request_id'], 'request_id')
    preview_id = integer(body['preview_id'], 'preview_id', 1)
    cue_id = text(body['cue_id'], 'cue_id')
    target = text(body['target'], 'target')
    transport = None
    if 'transport' in body:
        raw = fields(body['transport'], ('connection', 'short'))
        transport = (connection_name(raw['connection']), integer(raw['short'], 'short', 0, attempts.short_pool - 1))
    order = orders.accept_order(show, request_id, preview_id, cue_id, target)
    return 200, deliver_order(orders, attempts, lamps, order, transport).result()


def handle_lookup(orders, show, query):
    fields(query, ('show', 'request_id'))
    require_show(query['show'], show)
    return 200, orders.get_order(show, text(query['request_id'], 'request_id')).result()


def _dispatch_fact(orders, attempts, show, query):
    fields(query, ('show', 'connection', 'short'))
    require_show(query['show'], show)
    attempt = attempts.find_attempt(connection_name(query['connection']), query_integer(query['short'], 'short'))
    if attempt is None or attempt.show != show:
        raise ApiError(404, 'unknown_attempt', 'No accepted request owns this delivery attempt')
    return 200, orders.get_order(show, attempt.request_id).fact()


def _receive_report(orders, attempts, lamps, show, request):
    connections = request.headers.get_all(CONNECTION_HEADER) or []
    connection = connection_name(connections[0]) if len(connections) == 1 else None
    order = handle_short_report(orders, attempts, lamps, show, connection, request.body)
    return 200, order.result() if order is not None else {'status': 'unverified'}


def serve_duty(path, show, lamp_ports, port=0, short_pool=2):
    text(show, 'show')
    lamps = {text(lamp, 'lamp'): LampClient(integer(endpoint, 'lamp port', 1, 65535))
             for lamp, endpoint in lamp_ports.items()}
    scores, previews = ScoreStore(path), PreviewStore(path)
    orders, attempts, archive = OrderStore(path, previews), AttemptStore(path, short_pool), BookArchive(path)
    for store in (scores, previews, orders, attempts, archive):
        store.initialize()
    routes = {
        ('POST', '/score_write'): lambda req: handle_score_write(scores, show, req.body),
        ('GET', '/revision'): lambda req: handle_read_revision(scores, show, req.query),
        ('POST', '/preview'): lambda req: handle_preview(scores, previews, lamps, show, req.body),
        ('GET', '/preview'): lambda req: handle_read_preview(previews, show, req.query),
        ('POST', '/send'): lambda req: handle_send(orders, attempts, lamps, show, req.body),
        ('GET', '/lookup'): lambda req: handle_lookup(orders, show, req.query),
        ('GET', '/dispatch_fact'): lambda req: _dispatch_fact(orders, attempts, show, req.query),
        ('POST', '/report'): lambda req: _receive_report(orders, attempts, lamps, show, req),
        ('POST', '/close_book'): lambda req: handle_close_book(orders, lamps, archive, show, req.body),
        ('GET', '/read_book'): lambda req: handle_read_book(archive, show, req.query),
    }
    return make_server(port, routes)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Serve the rehearsal duty desk on loopback')
    parser.add_argument('--db', required=True)
    parser.add_argument('--show', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--short-pool', type=int, default=2)
    parser.add_argument('--lamp', action='append', default=[], metavar='LAMP=PORT')
    args = parser.parse_args(argv)
    roster = {}
    try:
        for entry in args.lamp:
            lamp, raw_port = entry.split('=', 1)
            if lamp in roster:
                raise ValueError(f'Duplicate lamp {lamp}')
            roster[lamp] = int(raw_port)
        integer(args.port, 'port', 1, 65535)
        server = serve_duty(args.db, args.show, roster, args.port, args.short_pool)
    except (ApiError, ValueError) as exc:
        parser.error(str(exc))
    with closing(server):
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return 0
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
