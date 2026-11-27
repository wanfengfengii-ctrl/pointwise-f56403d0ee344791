from dataclasses import asdict

from common import ApiError
from lamp.history import ActualFlash, find_attempt_flash
from lamp.store import LampStore


def record_or_replay(store: LampStore, delivery):
    with store.transaction() as db:
        by_attempt = find_attempt_flash(store, delivery.show, delivery.lamp,
                                        delivery.connection, delivery.short, db)
        flash = by_attempt
        if flash is None:
            record = store.load_request_flash(db, delivery.show, delivery.lamp, delivery.request_id)
            if record is not None:
                flash = ActualFlash.from_record(record)
        if flash is None:
            number = store.next_flash_number(db, delivery.show, delivery.lamp)
            flash = ActualFlash(delivery.show, delivery.lamp, number, delivery.request_id,
                                delivery.preview_id, delivery.cue)
            store.insert_flash(db, asdict(flash))
        elif (flash.request_id, flash.preview_id, flash.cue) != (delivery.request_id, delivery.preview_id, delivery.cue):
            raise ApiError(409, 'flash_conflict', 'Delivery differs from the committed flash')
        if by_attempt is None:
            store.link_attempt(db, delivery.show, delivery.lamp, delivery.connection, delivery.short, flash.number)
    return flash
