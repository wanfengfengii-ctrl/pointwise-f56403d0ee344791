from concurrent.futures import ThreadPoolExecutor

from tests.support import RehearsalTest


class DispatchTests(RehearsalTest):
    def test_ordinary_show_and_verified_attempt(self):
        preview = self.env.prepare()
        status, sent = self.env.send(preview, 'U', 'A', transport=('first', 0))
        self.assertEqual(status, 200)
        self.assertEqual((sent['status'], sent['actual_lamp'], sent['flash_number']), ('lit', 'alpha', 1))
        self.assertEqual(sent['cue']['text'], '吸气')
        self.assertEqual(sent['cue']['source'], {'revision': preview['revision'], 'section': '开场', 'cue_id': 'A'})
        self.assertEqual(self.env.get('/lookup', request_id='U'), (200, sent))
        status, observed = self.env.attempt_result('alpha', 'first', 0)
        self.assertEqual((status, observed['request_id'], observed['number']), (200, 'U', 1))
        self.assertEqual(observed['cue'], sent['cue'])
        self.assertEqual(self.env.flash('alpha', 1), (200, observed))
        self.assertEqual(self.env.flash('alpha', 2)[0], 404)
        self.assertEqual(self.env.get('/lookup', request_id='unknown')[1]['error'], 'unknown_request')

    def test_request_conflict_preserves_pending_parameters(self):
        preview = self.env.prepare()
        self.env.hold('alpha', 'U', 'before')
        status, original = self.env.send(preview, 'U', 'A')
        self.assertEqual((status, original['status']), (200, 'pending'))
        status, conflict = self.env.send(preview, 'U', 'C')
        self.assertEqual((status, conflict['error']), (409, 'request_conflict'))
        self.assertEqual(self.env.get('/lookup', request_id='U'), (200, original))
        self.assertEqual(len(self.env.relays['alpha'].executed), 1)
        self.assertEqual(self.env.flash('alpha', 1)[0], 404)

    def test_wrong_target_rejected_at_desk_and_lamp(self):
        preview = self.env.prepare()
        status, result = self.env.send(preview, 'U', 'A', target='beta')
        self.assertEqual((status, result['error']), (409, 'wrong_target'))
        self.assertEqual(self.env.get('/lookup', request_id='U')[0], 404)
        self.env.hold('alpha', 'U', 'before')
        self.assertEqual(self.env.send(preview, 'U', 'A')[1]['status'], 'pending')
        status, misdirected = self.env.execute_held('alpha', 'U', target='beta')
        self.assertEqual((status, misdirected['error']), (409, 'wrong_target'))
        self.assertEqual(self.env.flash('beta', 1)[0], 404)
        self.assertEqual(self.env.flash('alpha', 1)[0], 404)
        status, beta = self.env.send(preview, 'V', 'B')
        self.assertEqual((status, beta['actual_lamp'], beta['flash_number']), (200, 'beta', 1))

    def test_resume_lit_standard_retry_after_restart(self):
        preview = self.env.prepare()
        self.env.hold('alpha', 'U', 'after')
        status, waiting = self.env.send(preview, 'U', 'A')
        self.assertEqual((status, waiting['status']), (200, 'pending'))
        self.assertNotIn('flash_number', waiting)
        actual = self.env.flash('alpha', 1)
        self.assertEqual((actual[0], actual[1]['request_id']), (200, 'U'))
        first = self.env.relays['alpha'].executed[-1]
        self.env.restart()
        self.assertEqual(self.env.get('/lookup', request_id='U'), (200, waiting))
        status, resumed = self.env.send(preview, 'U', 'A')
        self.assertEqual((status, resumed['status'], resumed['flash_number']), (200, 'lit', 1))
        self.assertEqual(self.env.relays['alpha'].executed[-1], first)
        self.assertEqual(self.env.flash('alpha', 1), actual)
        self.assertEqual(self.env.flash('alpha', 2)[0], 404)

    def test_resume_before_display_and_unverified_report(self):
        preview = self.env.prepare()
        self.env.hold('alpha', 'U', 'before')
        status, waiting = self.env.send(preview, 'U', 'A')
        self.assertEqual((status, waiting['status']), (200, 'pending'))
        first = self.env.relays['alpha'].executed[-1]
        _, connection, short = first
        self.assertEqual(self.env.report(None, {'short': short}), (200, {'status': 'unverified'}))
        self.assertEqual(self.env.report('unknown', {'short': short}), (200, {'status': 'unverified'}))
        self.assertEqual(self.env.report(connection, {'short': short}), (200, waiting))
        self.assertEqual(self.env.get('/lookup', request_id='U'), (200, waiting))
        self.assertEqual(self.env.flash('alpha', 1)[0], 404)
        self.env.restart()
        status, lit = self.env.send(preview, 'U', 'A')
        self.assertEqual((status, lit['status'], lit['flash_number']), (200, 'lit', 1))
        self.assertEqual(self.env.relays['alpha'].executed[-1], first)
        self.assertEqual(self.env.flash('alpha', 2)[0], 404)

    def test_reused_short_delayed_reply_and_reopened_replay(self):
        preview = self.env.prepare()
        self.env.hold('alpha', 'U', 'after')
        self.assertEqual(self.env.send(preview, 'U', 'A', transport=('old', 0))[1]['status'], 'pending')
        self.assertEqual(self.env.send(preview, 'W', 'B', transport=('other', 1))[1]['flash_number'], 1)
        self.env.hold('beta', 'V', 'before')
        self.assertEqual(self.env.send(preview, 'V', 'B', transport=('new', 0))[1]['status'], 'pending')
        status, received = self.env.release_report('alpha', 'U')
        self.assertEqual((status, received['request_id'], received['flash_number']), (200, 'U', 1))
        status, waiting = self.env.get('/lookup', request_id='V')
        self.assertEqual((status, waiting['status']), (200, 'pending'))
        self.assertNotIn('flash_number', waiting)
        self.assertEqual(self.env.flash('beta', 2)[0], 404)
        self.assertEqual(self.env.close_book(), (200, {'status': 'pending', 'pending': ['V']}))
        self.env.restart()
        status, replay = self.env.send(preview, 'U', 'A', transport=('retry', 1))
        self.assertEqual((status, replay['request_id'], replay['flash_number']), (200, 'U', 1))
        self.assertEqual(self.env.attempt_result('alpha', 'retry', 1), self.env.flash('alpha', 1))
        self.assertEqual(self.env.flash('alpha', 2)[0], 404)
        self.assertEqual(self.env.execute_held('beta', 'V'), (200, {'short': 0}))
        status, result = self.env.release_report('beta', 'V')
        self.assertEqual((status, result['request_id'], result['actual_lamp'], result['flash_number']), (200, 'V', 'beta', 2))
        self.assertEqual(self.env.release_report('alpha', 'U'), (200, received))
        status, book = self.env.close_book()
        self.assertEqual(status, 200)
        actual = [(row['request_id'], row['lamp'], row['number']) for row in book['entries']]
        self.assertEqual(actual, [('U', 'alpha', 1), ('W', 'beta', 1), ('V', 'beta', 2)])
        self.assertEqual(self.env.get('/read_book', book_id=book['book_id']), (200, book))

    def test_new_report_can_arrive_first(self):
        preview = self.env.prepare()
        self.env.hold('alpha', 'U', 'after')
        self.env.send(preview, 'U', 'A', transport=('earlier', 0))
        status, later = self.env.send(preview, 'V', 'B', transport=('later', 0))
        self.assertEqual((status, later['status'], later['actual_lamp']), (200, 'lit', 'beta'))
        self.assertEqual(self.env.get('/lookup', request_id='U')[1]['status'], 'pending')
        status, earlier = self.env.release_report('alpha', 'U')
        self.assertEqual((status, earlier['status'], earlier['actual_lamp']), (200, 'lit', 'alpha'))
        self.assertEqual(self.env.get('/lookup', request_id='V'), (200, later))

    def test_changed_transport_before_and_after_commit(self):
        preview = self.env.prepare()
        self.env.hold('alpha', 'U', 'after')
        self.env.hold('beta', 'V', 'before')
        for request, cue, connection in (('U', 'A', 'alpha-old'), ('V', 'B', 'beta-old')):
            self.assertEqual(self.env.send(preview, request, cue, transport=(connection, 0))[1]['status'], 'pending')
        self.assertEqual(self.env.flash('alpha', 1)[0], 200)
        self.assertEqual(self.env.flash('beta', 1)[0], 404)
        self.env.restart()
        for request, cue, lamp in (('U', 'A', 'alpha'), ('V', 'B', 'beta')):
            status, result = self.env.send(preview, request, cue, transport=(lamp + '-retry', 1))
            self.assertEqual((status, result['status'], result['actual_lamp'], result['flash_number']), (200, 'lit', lamp, 1))
            self.assertEqual(self.env.flash(lamp, 1)[1]['request_id'], request)
            self.assertEqual(self.env.flash(lamp, 2)[0], 404)
        self.assertEqual(self.env.execute_held('beta', 'V'), (200, {'short': 0}))
        self.assertEqual(self.env.flash('beta', 2)[0], 404)
        status, conflict = self.env.send(preview, 'U', 'C', transport=('bad-retry', 0))
        self.assertEqual((status, conflict['error']), (409, 'request_conflict'))
        self.assertEqual(self.env.flash('alpha', 2)[0], 404)

    def test_concurrent_transports_share_one_flash(self):
        preview = self.env.prepare()
        with ThreadPoolExecutor(max_workers=2) as workers:
            requests = [workers.submit(self.env.send, preview, 'U', 'A', transport=(f'link-{short}', short))
                        for short in range(2)]
            for request in requests:
                status, result = request.result()
                self.assertEqual((status, result['status'], result['flash_number']), (200, 'lit', 1))
        self.assertEqual(self.env.attempt_result('alpha', 'link-0', 0), self.env.flash('alpha', 1))
        self.assertEqual(self.env.attempt_result('alpha', 'link-1', 1), self.env.flash('alpha', 1))
        self.assertEqual(self.env.flash('alpha', 2)[0], 404)
