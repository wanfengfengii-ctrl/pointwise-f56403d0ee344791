from dispatch.attempts import AttemptStore
from dispatch.orders import DispatchOrder, OrderStore
from dispatch.settlement import settle_order
from lamp.http import LampClient
from wire import WireError


def handle_short_report(orders: OrderStore, attempts: AttemptStore, lamps: dict[str, LampClient],
                        show, connection, report, *, expected_short=None):
    if not isinstance(report, dict) or report.keys() != {'short'}:
        return None
    short = report['short']
    if type(short) is not int or not 0 <= short < 2**63:
        return None
    if connection is None or (expected_short is not None and short != expected_short):
        return None
    attempt = attempts.find_attempt(connection, short)
    if attempt is None or attempt.show != show:
        return None
    order = orders.get_order(show, attempt.request_id)
    lamp = lamps.get(order.cue.lamp)
    if lamp is None:
        return order
    try:
        flash = lamp.read_attempt_result(show, connection, short)
    except WireError:
        return orders.get_order(show, attempt.request_id)
    return settle_order(orders, order, flash)


def deliver_order(orders, attempts, lamps, order: DispatchOrder, transport=None):
    if order.flash_number is not None and transport is None:
        return order
    lamp = lamps.get(order.cue.lamp)
    if lamp is None:
        return order
    attempt = attempts.record_attempt(order, transport)
    try:
        report = lamp.execute(order.fact(), attempt.connection, attempt.short)
    except WireError:
        return orders.get_order(order.show, order.request_id)
    settled = handle_short_report(orders, attempts, lamps, order.show, attempt.connection, report,
                                  expected_short=attempt.short)
    return settled if settled is not None else orders.get_order(order.show, order.request_id)
