import json
from tempfile import TemporaryDirectory

from tests.support import Rehearsal, sample


def require(actual, expected):
    if actual != expected:
        raise AssertionError(f'Expected {expected!r}, received {actual!r}')


def main():
    with TemporaryDirectory(prefix='qinghe-demo-') as directory, Rehearsal(directory) as rehearsal:
        preview = rehearsal.prepare()
        expected_plan = [[4, 'A', 'alpha'], [4, 'B', 'beta'], [8, 'C', 'alpha']]
        planned = [[item['beat'], item['source']['cue_id'], item['lamp']] for item in preview['cues']]
        require(planned, expected_plan)
        rehearsal.hold('alpha', 'U', 'after')
        status, first = rehearsal.send(preview, 'U', 'A')
        require((status, first['status']), (200, 'pending'))
        require(rehearsal.flash('alpha', 1)[1]['request_id'], 'U')
        status, second = rehearsal.send(preview, 'V', 'B')
        require((status, second['status']), (200, 'lit'))
        require(rehearsal.close_book(), (200, {'status': 'pending', 'pending': ['U']}))
        rehearsal.restart()
        status, resumed = rehearsal.send(preview, 'U', 'A')
        require((status, resumed['status'], resumed['flash_number']), (200, 'lit', 1))
        require(rehearsal.flash('alpha', 2)[0], 404)
        status, book = rehearsal.close_book()
        require((status, book['status']), (200, 'closed'))
        status, reopened = rehearsal.get('/read_book', book_id=book['book_id'])
        require((status, reopened), (200, book))
        expected_book = [['U', 'alpha', 1, 'A', '吸气'], ['V', 'beta', 1, 'B', '收声']]
        archived = [[row['request_id'], row['lamp'], row['number'], row['cue']['source']['cue_id'], row['cue']['text']]
                    for row in reopened['entries']]
        require(archived, expected_book)
        for row in reopened['entries']:
            require(row['cue']['source']['revision'], preview['revision'])
        evidence = {
            'case_id': 'cue_order', 'input': sample(), 'expected': expected_plan, 'actual': planned,
            'downstream_expected': expected_book, 'downstream_actual': archived,
            'code_paths': ['score/revisions.py', 'plan/targets.py', 'plan/order.py', 'plan/preview.py',
                           'dispatch/delivery.py', 'lamp/display.py', 'review/snapshot.py', 'review/archive.py'],
            'oracle': '手按两张第4拍的原稿先后及第8拍排出 A/B/C。演示只投 A 和 B，各台首笔实际点亮均为 1。',
        }
        print('POINTWISE_SCENARIO ' + json.dumps(evidence, ensure_ascii=False))
        print(json.dumps(reopened, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
