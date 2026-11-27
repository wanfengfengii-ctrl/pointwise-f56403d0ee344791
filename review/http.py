from common import fields, query_integer, require_show
from review.archive import BookArchive
from review.close import close_book


def handle_close_book(orders, lamps, archive: BookArchive, show, body):
    fields(body, ('show',))
    require_show(body['show'], show)
    return 200, close_book(orders, lamps, archive, show).result()


def handle_read_book(archive: BookArchive, show, query):
    fields(query, ('show', 'book_id'))
    require_show(query['show'], show)
    return 200, archive.read_book(show, query_integer(query['book_id'], 'book_id', 1))
