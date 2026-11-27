from dispatch.orders import DispatchOrder, OrderStore
from lamp.history import ActualFlash


def matches_flash(order: DispatchOrder, flash: ActualFlash):
    return (flash.show == order.show and flash.request_id == order.request_id
            and flash.preview_id == order.preview_id and flash.lamp == order.cue.lamp
            and flash.cue == order.cue and type(flash.number) is int and flash.number > 0)


def settle_order(orders: OrderStore, order: DispatchOrder, flash: ActualFlash | None):
    if flash is None or not matches_flash(order, flash):
        return orders.get_order(order.show, order.request_id)
    return orders.mark_lit(order.show, order.request_id, flash.lamp, flash.number)
