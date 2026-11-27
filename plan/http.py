from dataclasses import asdict

from common import fields, integer, query_integer, require_show
from plan.preview import freeze_preview, read_preview


def handle_preview(scores, previews, roster, show, body):
    fields(body, ('show', 'revision', 'section', 'assignments'))
    require_show(body['show'], show)
    plan = freeze_preview(scores, previews, show, integer(body['revision'], 'revision', 1),
                          body['section'], body['assignments'], roster)
    return 201, asdict(plan)


def handle_read_preview(previews, show, query):
    fields(query, ('show', 'preview_id'))
    require_show(query['show'], show)
    preview_id = query_integer(query['preview_id'], 'preview_id', 1)
    return 200, asdict(read_preview(previews, show, preview_id))
