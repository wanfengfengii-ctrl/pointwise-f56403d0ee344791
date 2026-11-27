from tests.support import RehearsalTest, SHOW, sample


class ReviewTests(RehearsalTest):
    def test_pending_book_waiting_then_closed(self):
        preview = self.env.prepare()
        self.assertEqual(self.env.send(preview, 'U', 'A')[1]['status'], 'lit')
        self.env.hold('beta', 'V', 'after')
        self.assertEqual(self.env.send(preview, 'V', 'B')[1]['status'], 'pending')
        self.assertEqual(self.env.flash('beta', 1)[1]['request_id'], 'V')
        self.assertEqual(self.env.close_book(), (200, {'status': 'pending', 'pending': ['V']}))
        self.assertEqual(self.env.duty_counts()[-1], 0)
        self.assertEqual(self.env.get('/read_book', book_id=1)[0], 404)
        self.assertEqual(self.env.release_report('beta', 'V')[1]['status'], 'lit')
        status, book = self.env.close_book()
        self.assertEqual((status, book['status']), (200, 'closed'))
        self.assertEqual([(row['request_id'], row['lamp'], row['number']) for row in book['entries']],
                         [('U', 'alpha', 1), ('V', 'beta', 1)])
        self.assertEqual(self.env.get('/read_book', book_id=book['book_id']), (200, book))

    def test_read_closed_actual_order_and_immutable_source(self):
        preview = self.env.prepare()
        self.env.hold('alpha', 'U', 'before')
        self.assertEqual(self.env.send(preview, 'U', 'A')[1]['status'], 'pending')
        self.assertEqual(self.env.send(preview, 'X', 'C')[1]['flash_number'], 1)
        self.assertEqual(self.env.send(preview, 'V', 'B')[1]['flash_number'], 1)
        self.assertEqual(self.env.execute_held('alpha', 'U')[0], 200)
        self.assertEqual(self.env.release_report('alpha', 'U')[1]['flash_number'], 2)
        status, book = self.env.close_book()
        self.assertEqual(status, 200)
        rows = [(entry['lamp'], entry['number'], entry['cue']['source']['cue_id'], entry['cue']['text'])
                for entry in book['entries']]
        self.assertEqual(rows, [('alpha', 1, 'C', '延长'), ('alpha', 2, 'A', '吸气'), ('beta', 1, 'B', '收声')])
        for entry in book['entries']:
            self.assertEqual(entry['cue']['source']['revision'], preview['revision'])
            self.assertEqual(entry['cue']['source']['section'], '开场')
        replacement = sample()['score']
        replacement['cues'][0]['text'] = '缓吸'
        replacement['cues'][2]['text'] = '渐弱'
        status, revised = self.env.post('/score_write', replacement)
        self.assertEqual(status, 201)
        self.assertNotEqual(revised['revision'], preview['revision'])
        self.env.restart()
        self.assertEqual(self.env.get('/preview', preview_id=preview['preview_id']), (200, preview))
        self.assertEqual(self.env.get('/read_book', book_id=book['book_id']), (200, book))
        self.assertEqual(self.env.duty_counts(), (2, 6, 1, 1))
        status, result = self.env.get('/read_book', book_id=book['book_id'] + 1)
        self.assertEqual((status, result['error']), (404, 'unknown_book'))

    def test_empty_show_seals_empty_book(self):
        self.assertEqual(self.env.post('/close_book', {'show': 'other'})[0], 404)
        status, book = self.env.close_book()
        self.assertEqual((status, book['status'], book['show'], book['entries']), (200, 'closed', SHOW, []))
        self.assertEqual(self.env.get('/read_book', book_id=book['book_id']), (200, book))
