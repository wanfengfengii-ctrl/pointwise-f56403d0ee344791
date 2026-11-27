from dataclasses import asdict

from common import fields, query_integer, require_show
from score.revisions import read_revision, write_score


def handle_score_write(store, show, body):
    fields(body, ('show', 'sections', 'cues'))
    require_show(body['show'], show)
    revision = write_score(store, show, body['sections'], body['cues'])
    return 201, {'show': show, 'revision': revision.revision,
                 'sources': [asdict(cue.source(revision.revision)) for cue in revision.cues]}


def handle_read_revision(store, show, query):
    fields(query, ('show', 'revision'))
    require_show(query['show'], show)
    revision = read_revision(store, show, query_integer(query['revision'], 'revision', 1))
    return 200, asdict(revision)
