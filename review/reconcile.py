from dataclasses import dataclass

from dispatch.orders import OrderStore
from dispatch.settlement import matches_flash
from lamp.history import ActualFlash
from lamp.http import LampClient
from wire import WireError


@dataclass(frozen=True)
class Reconciliation:
    verified: tuple[ActualFlash, ...]
    pending: tuple[str, ...]


def reconcile_show(orders: OrderStore, lamps: dict[str, LampClient], show):
    verified = []
    pending = []
    for order in orders.list_show_orders(show):
        lamp = lamps.get(order.actual_lamp)
        if order.flash_number is None or lamp is None:
            pending.append(order.request_id)
            continue
        try:
            flash = lamp.read_flash(show, order.flash_number)
        except WireError:
            flash = None
        if (flash is None or flash.lamp != order.actual_lamp or flash.number != order.flash_number
                or not matches_flash(order, flash)):
            pending.append(order.request_id)
        else:
            verified.append(flash)
    return Reconciliation(tuple(verified), tuple(pending))
