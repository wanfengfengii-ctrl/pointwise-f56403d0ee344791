import time
from concurrent.futures import ThreadPoolExecutor
from tempfile import TemporaryDirectory

from pause_fixture import ExchangeGate, PauseRehearsal
from tests.support import RehearsalTest, SHOW


class PauseTests(RehearsalTest):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory(prefix='qinghe-pause-test-'))
        self.env = self.enterContext(PauseRehearsal(directory))

    def _scenario(self, *, unlit='Z'):
        plan = self.env.prepare()
        self.assertEqual(self.env.send(plan, 'U', 'A')[1]['flash_number'], 1)
        self.env.hold('alpha', 'X', 'after')
        x = self.env.send(plan, 'X', 'C')[1]
        self.assertEqual(x['status'], 'pending')
        self.assertEqual(self.env.send(plan, 'V', 'B')[1]['flash_number'], 1)
        # An accepted but never displayed card must never enter a pause book.
        self.env.hold('alpha', unlit, 'before')
        self.assertEqual(self.env.send(plan, unlit, 'C')[1]['status'], 'pending')
        return plan

    def _assert_book_shape(self, sealed, plan, expected_heads, expected_requests):
        self.assertEqual(sealed['show'], SHOW)
        self.assertEqual(sealed['status'], 'sealed')
        self.assertEqual(sealed['heads'], expected_heads)
        entries = sealed['entries']
        self.assertEqual([entry['request_id'] for entry in entries], expected_requests)
        self.assertEqual(entries, sorted(entries, key=lambda row: (row['lamp'], row['number'])))
        for entry in entries:
            self.assertEqual(set(entry), {'request_id', 'lamp', 'number', 'preview_id', 'cue'})
            cue = next(item for item in plan['cues'] if item['source']['cue_id'] == entry['cue']['source']['cue_id'])
            self.assertEqual(entry['cue'], cue)
            self.assertEqual(entry['preview_id'], plan['preview_id'])
        return entries

    def test_interleaved_cutline_keeps_lit_unreported_and_excludes_unlit(self):
        plan = self._scenario()
        status, sealed = self.env.mark_pause('P1')
        self.assertEqual(status, 200)
        entries = self._assert_book_shape(sealed, plan, {'alpha': 2, 'beta': 1}, ['U', 'X', 'V'])
        x_entry = next(entry for entry in entries if entry['request_id'] == 'X')
        self.assertEqual((x_entry['lamp'], x_entry['number'], x_entry['cue']['text']),
                         ('alpha', 2, '延长'))
        # The cross-lamp pair that never coexisted must not be the sealed cutline.
        self.assertNotEqual(sealed['heads'], {'alpha': 1, 'beta': 1})
        # Original settlement state is untouched: X stays pending, Z never lit.
        self.assertEqual(self.env.get('/lookup', request_id='X')[1]['status'], 'pending')
        self.assertEqual(self.env.get('/lookup', request_id='Z')[1]['status'], 'pending')
        self.assertEqual(self.env.flash('alpha', 3)[0], 404)
        # Re-marking and reading the same id returns the identical fixed book.
        self.assertEqual(self.env.mark_pause('P1'), (200, sealed))
        self.assertEqual(self.env.read_pause('P1'), (200, sealed))
        self.assertEqual(self.env.read_pause('MISSING')[0], 404)

    def test_continuous_dispatches_only_held_lamp_waits(self):
        plan = self.env.prepare()
        self.assertEqual(self.env.send(plan, 'U', 'A')[1]['flash_number'], 1)
        self.assertEqual(self.env.send(plan, 'V', 'B')[1]['flash_number'], 1)
        gate = ExchangeGate('POST', '/pause_marker', after=True)
        self.env.relays['alpha'].gate = gate

        def mark():
            return self.env.mark_pause('P1')

        with ThreadPoolExecutor(max_workers=3) as workers:
            mark_future = workers.submit(mark)
            self.assertTrue(gate.reached.wait(3))
            # While alpha is held by the armed marker, beta keeps serving first lights.
            beta_new = workers.submit(self.env.send, plan, 'W', 'B')
            status, beta_result = beta_new.result()
            self.assertEqual((status, beta_result['status'], beta_result['flash_number']),
                             (200, 'lit', 2))
            # Alpha's ordinary first light is the one lamp that briefly waits.
            self.env.hold('alpha', 'Q', 'after')
            alpha_new = workers.submit(self.env.send, plan, 'Q', 'C')
            time.sleep(0.15)
            self.assertEqual(self.env.flash('alpha', 2)[0], 404)
            gate.resume.set()
            status, sealed = mark_future.result()
            status_q, q = alpha_new.result()
        self.env.relays['alpha'].gate = None
        self.assertEqual(status, 200)
        self.assertEqual(sealed['status'], 'sealed')
        # The sealed heads were a real coexisting pair observed while alpha was held.
        self.assertEqual(sealed['heads']['alpha'], 1)
        self.assertIn(sealed['heads']['beta'], (1, 2))
        # Q's lamp-side first light was committed after the brief hold; its report
        # is intentionally held, so the desk order stays pending until released.
        self.assertEqual((status_q, q['status']), (200, 'pending'))
        self.assertEqual(self.env.flash('alpha', 2)[1]['request_id'], 'Q')
        status, released = self.env.release_report('alpha', 'Q')
        self.assertEqual((status, released['status'], released['flash_number']), (200, 'lit', 2))
        self.assertEqual([entry['request_id'] for entry in sealed['entries']],
                         ['U'] + (['V', 'W'] if sealed['heads']['beta'] == 2 else ['V']))
        # Every sealed prefix flash still reads back from the real lamps.
        for entry in sealed['entries']:
            status, flash = self.env.flash(entry['lamp'], entry['number'])
            self.assertEqual((status, flash['request_id']), (200, entry['request_id']))

    def test_marker_failure_leaves_pending_then_same_id_resumes(self):
        plan = self._scenario()
        gate = ExchangeGate('POST', '/pause_marker', reject=True)
        self.env.relays['alpha'].gate = gate
        self.assertEqual(self.env.mark_pause('P1'),
                         (200, {'show': SHOW, 'mark_id': 'P1', 'status': 'pending'}))
        self.assertEqual(self.env.read_pause('P1'),
                         (200, {'show': SHOW, 'mark_id': 'P1', 'status': 'pending'}))
        # Online lamps continue ordinary first lights while the mark is pending.
        self.assertEqual(self.env.send(plan, 'W', 'B')[1]['flash_number'], 2)
        # Retry with the same id now succeeds and seals the current common cutline.
        self.env.relays['alpha'].gate = None
        status, sealed = self.env.mark_pause('P1')
        self.assertEqual(status, 200)
        self.assertEqual(sealed['heads'], {'alpha': 2, 'beta': 2})
        self._assert_book_shape(sealed, plan, {'alpha': 2, 'beta': 2}, ['U', 'X', 'V', 'W'])
        self.assertEqual(self.env.read_pause('P1'), (200, sealed))

    def test_marker_reply_lost_then_replay_reseals_pending_mark(self):
        plan = self._scenario()
        # The marker reaches and arms the lamp, but its reply is lost to the desk.
        gate = ExchangeGate('POST', '/pause_marker', after=True, reject=True)
        self.env.relays['alpha'].gate = gate
        self.assertEqual(self.env.mark_pause('P2')[1]['status'], 'pending')
        self.env.relays['alpha'].gate = None
        # The desk's retry is an idempotent replay on the lamp; the mark then seals.
        status, sealed = self.env.mark_pause('P2')
        self.assertEqual(status, 200)
        self.assertEqual(sealed['heads'], {'alpha': 2, 'beta': 1})
        self._assert_book_shape(sealed, plan, {'alpha': 2, 'beta': 1}, ['U', 'X', 'V'])

    def test_head_read_failure_is_pending_and_retry_seals(self):
        plan = self._scenario()
        gate = ExchangeGate('GET', '/pause_head', reject=True)
        self.env.relays['beta'].gate = gate
        self.assertEqual(self.env.mark_pause('P3')[1]['status'], 'pending')
        self.env.relays['beta'].gate = None
        status, sealed = self.env.mark_pause('P3')
        self.assertEqual(status, 200)
        self.assertEqual(sealed['heads'], {'alpha': 2, 'beta': 1})
        self._assert_book_shape(sealed, plan, sealed['heads'], ['U', 'X', 'V'])

    def test_hold_ttl_expires_ordinary_light_proceeds_and_rearm_works(self):
        with TemporaryDirectory(prefix='qinghe-ttl-') as directory, \
                PauseRehearsal(directory, pause_ttl=0.15) as short_env:
            plan = short_env.prepare()
            short_env.send(plan, 'U', 'A')
            status, marker = short_env.relay_call('alpha', 'POST', '/pause_marker',
                                                  {'show': SHOW, 'mark_id': 'T1'})
            self.assertEqual((status, marker['head'], marker['replay']), (200, 1, False))
            # The held lamp blocks a new first light only until the TTL passes.
            with ThreadPoolExecutor(max_workers=1) as workers:
                future = workers.submit(short_env.send, plan, 'X', 'C')
                time.sleep(0.4)
                status, lit = future.result()
            self.assertEqual((status, lit['status'], lit['flash_number']), (200, 'lit', 2))
            # TTL lapsed before sealing: re-arm under the same mark id and seal.
            short_env.relay_call('alpha', 'POST', '/pause_marker', {'show': SHOW, 'mark_id': 'T1'})
            status, sealed = short_env.mark_pause('T1')
            self.assertEqual(status, 200)
            self.assertEqual(sealed['heads'], {'alpha': 2, 'beta': 0})
            self._assert_book_shape(sealed, plan, {'alpha': 2, 'beta': 0}, ['U', 'X'])

    def test_sealed_book_survives_duty_restart_with_both_lamps_offline(self):
        plan = self._scenario()
        status, sealed = self.env.mark_pause('P4')
        self.assertEqual(status, 200)
        # Take both lamps fully offline, then reopen only the desk on its database.
        for lamp in ('alpha', 'beta'):
            self.env.stop_lamp(lamp)
        self.env.restart_duty()
        self.assertEqual(self.env.read_pause('P4'), (200, sealed))
        # Re-posting the same mark while offline cannot re-prove a cutline,
        # but it returns the original sealed book rather than overwriting it.
        self.assertEqual(self.env.mark_pause('P4'), (200, sealed))
        self.assertEqual(self.env.read_pause('MISSING')[0], 404)

    def test_pause_takes_no_extra_flashes_and_original_dispatch_keeps_working(self):
        plan = self._scenario()
        _, sealed = self.env.mark_pause('P5')
        self.assertEqual(sealed['heads'], {'alpha': 2, 'beta': 1})
        # No marker machinery creates flashes; Z was accepted but never displayed.
        self.assertEqual(self.env.flash('alpha', 3)[0], 404)
        self.assertEqual(self.env.flash('beta', 2)[0], 404)
        # Releasing X's held report still settles the original order normally.
        status, reported = self.env.release_report('alpha', 'X')
        self.assertEqual((status, reported['status'], reported['flash_number']), (200, 'lit', 2))
        # The pause book remains fixed at its original cutline and pending record.
        self.assertEqual(self.env.read_pause('P5'), (200, sealed))
        x_entry = next(entry for entry in sealed['entries'] if entry['request_id'] == 'X')
        self.assertEqual((x_entry['lamp'], x_entry['number']), ('alpha', 2))
        # The original end-of-show flow still works and excludes the never-lit Z.
        status, book = self.env.close_book()
        self.assertEqual(status, 200)
        self.assertEqual(book['status'], 'pending')
        self.assertEqual(book['pending'], ['Z'])

    def test_empty_show_and_independent_marks(self):
        status, empty = self.env.mark_pause('EMPTY')
        self.assertEqual((status, empty['status'], empty['heads'], empty['entries']),
                         (200, 'sealed', {'alpha': 0, 'beta': 0}, []))
        self.assertEqual(self.env.read_pause('EMPTY'), (200, empty))
        plan = self.env.prepare()
        self.env.send(plan, 'U', 'A')
        status, first = self.env.mark_pause('P1')
        self.assertEqual(first['heads'], {'alpha': 1, 'beta': 0})
        self.env.send(plan, 'V', 'B')
        status, second = self.env.mark_pause('P2')
        self.assertEqual(second['heads'], {'alpha': 1, 'beta': 1})
        self.assertEqual(self.env.read_pause('P1'), (200, first))
        self.assertEqual(self.env.read_pause('P2'), (200, second))
        self.assertNotEqual(first['entries'], second['entries'])

    def test_pending_mark_resumes_after_both_lamps_restart_on_same_databases(self):
        plan = self.env.prepare()
        self.env.send(plan, 'U', 'A')
        gate = ExchangeGate('POST', '/pause_marker', after=True, reject=True)
        self.env.relays['alpha'].gate = gate
        self.assertEqual(self.env.mark_pause('P1')[1]['status'], 'pending')
        self.env.relays['alpha'].gate = None
        for lamp in ('alpha', 'beta'):
            self.env.stop_lamp(lamp)
            self.env._start_lamp(lamp)
        self.assertEqual(self.env.send(plan, 'V', 'B')[1]['flash_number'], 1)
        status, sealed = self.env.mark_pause('P1')
        self.assertEqual(status, 200)
        self.assertEqual(sealed['heads'], {'alpha': 1, 'beta': 1})
        self._assert_book_shape(sealed, plan, {'alpha': 1, 'beta': 1}, ['U', 'V'])

    def test_invalid_pause_requests(self):
        self.env.prepare()
        for bad in ('', '   '):
            status, result = self.env.post('/mark_pause', {'show': SHOW, 'mark_id': bad})
            self.assertEqual((status, result['error']), (400, 'invalid_text'))
        self.assertEqual(self.env.post('/mark_pause', {'show': 'other', 'mark_id': 'P'})[0], 404)
        self.assertEqual(self.env.post('/mark_pause', {'mark_id': 'P'})[0], 400)
        self.assertEqual(self.env.get('/read_pause', mark_id='P')[0], 404)
