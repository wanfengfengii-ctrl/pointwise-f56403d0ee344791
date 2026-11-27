from dataclasses import dataclass

from common import ApiError, encode, fields, integer, require_show, text
from lamp.display import record_or_replay
from plan.order import PlannedCue


@dataclass(frozen=True)
class ExecutionInput:
    show: str
    lamp: str
    request_id: str
    preview_id: int
    cue: PlannedCue
    connection: str
    short: int


def validate_delivery(show, lamp, body, connection, fact):
    fields(body, ('show', 'request_id', 'preview_id', 'cue', 'short'))
    require_show(body['show'], show)
    short = integer(body['short'], 'short')
    delivered_fact = {key: body[key] for key in ('show', 'request_id', 'preview_id', 'cue')}
    if fact is None or encode(delivered_fact) != encode(fact):
        raise ApiError(409, 'unverified_delivery', 'Delivery differs from the accepted dispatch fact')
    cue = PlannedCue.from_record(fact['cue'])
    if cue.lamp != lamp:
        raise ApiError(409, 'wrong_target', 'Accepted cue belongs to another lamp')
    return ExecutionInput(show, lamp, text(fact['request_id'], 'request_id'),
                          integer(fact['preview_id'], 'preview_id', 1), cue, connection, short)


def execute_cue(store, show, lamp, body, connection, fact):
    delivery = validate_delivery(show, lamp, body, connection, fact)
    return record_or_replay(store, delivery)
