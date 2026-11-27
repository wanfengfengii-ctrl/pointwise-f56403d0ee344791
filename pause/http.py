from common import fields, require_show, text
from pause.snapshot import PauseService


def handle_mark_pause(service: PauseService, show, body):
    fields(body, ('show', 'mark_id'))
    require_show(body['show'], show)
    return 200, service.mark(show, text(body['mark_id'], 'mark_id'))


def handle_read_pause(service: PauseService, show, query):
    fields(query, ('show', 'mark_id'))
    require_show(query['show'], show)
    return 200, service.read(show, text(query['mark_id'], 'mark_id'))
