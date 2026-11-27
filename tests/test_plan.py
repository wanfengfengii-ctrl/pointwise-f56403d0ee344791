from copy import deepcopy

from tests.support import RehearsalTest, SHOW, sample


class PlanTests(RehearsalTest):
    def test_cue_order_equal_beat_input_order(self):
        score = sample()['score']
        a, b, c = score['cues']
        score['cues'] = [c, b, a]
        preview = self.env.prepare(score)
        actual = [(cue['source']['cue_id'], cue['beat'], cue['position'], cue['lamp']) for cue in preview['cues']]
        self.assertEqual(actual, [('B', 4, 1, 'beta'), ('A', 4, 2, 'alpha'), ('C', 8, 0, 'alpha')])
        self.assertEqual([cue['source']['revision'] for cue in preview['cues']], [preview['revision']] * 3)
        self.assertEqual([cue['source']['section'] for cue in preview['cues']], ['开场'] * 3)
        self.assertEqual(self.env.get('/preview', preview_id=preview['preview_id']), (200, preview))

    def test_empty_section_and_select_only_requested(self):
        score = sample()['score']
        score['sections'].append('尾声')
        score['cues'].append({'id': 'D', 'section': '尾声', 'voice': '领唱', 'beat': 0, 'text': '齐声'})
        preview = self.env.prepare(score)
        self.assertEqual([cue['source']['cue_id'] for cue in preview['cues']], ['A', 'B', 'C'])
        body = {'show': SHOW, 'revision': preview['revision'], 'section': '休息', 'assignments': {}}
        status, rest = self.env.post('/preview', body)
        self.assertEqual(status, 201)
        self.assertEqual(rest['cues'], [])
        self.assertEqual(self.env.get('/preview', preview_id=rest['preview_id']), (200, rest))
        status, ending = self.env.post('/preview', {**body, 'section': '尾声', 'assignments': {'领唱': 'beta'}})
        self.assertEqual(status, 201)
        self.assertEqual([(cue['source']['cue_id'], cue['lamp']) for cue in ending['cues']], [('D', 'beta')])
        self.assertEqual(self.env.post('/preview', {**body, 'section': '无此段'})[1]['error'], 'unknown_section')

    def test_invalid_score_atomic_reject(self):
        good = self.env.prepare()
        counts = self.env.duty_counts()
        original_revision = self.env.get('/revision', revision=good['revision'])
        self.assertEqual(original_revision[0], 200)
        for invalid in (-1, 1.5, True, None, '4', 'missing', 'undeclared'):
            with self.subTest(invalid=invalid):
                score = deepcopy(sample()['score'])
                tail = score['cues'][-1]
                if invalid == 'missing':
                    del tail['beat']
                    error = 'invalid_fields'
                elif invalid == 'undeclared':
                    tail['section'] = '未声明'
                    error = 'unknown_section'
                else:
                    tail['beat'] = invalid
                    error = 'invalid_beat'
                status, result = self.env.post('/score_write', score)
                self.assertEqual((status, result['error']), (400, error))
                self.assertEqual(self.env.duty_counts(), counts)
                self.assertEqual(self.env.get('/preview', preview_id=good['preview_id']), (200, good))
                self.assertEqual(self.env.get('/revision', revision=good['revision']), original_revision)

    def test_frozen_targets_and_missing_assignment(self):
        original = self.env.prepare()
        body = {'show': SHOW, 'revision': original['revision'], 'section': '开场'}
        counts = self.env.duty_counts()
        for assignments in ({'高声部': 'alpha'}, {'高声部': 'unlisted', '低声部': 'beta'}):
            status, result = self.env.post('/preview', {**body, 'assignments': assignments})
            self.assertEqual((status, result['error']), (400, 'missing_target'))
        self.assertEqual(self.env.post('/preview', {**body, 'revision': 99, 'assignments': {}})[0], 404)
        self.assertEqual(self.env.duty_counts(), counts)
        status, changed = self.env.post('/preview', {**body, 'assignments': {'高声部': 'beta', '低声部': 'alpha'}})
        self.assertEqual(status, 201)
        self.assertEqual([cue['lamp'] for cue in changed['cues']], ['beta', 'alpha', 'beta'])
        self.assertEqual([cue['lamp'] for cue in original['cues']], ['alpha', 'beta', 'alpha'])
        self.assertEqual(self.env.get('/preview', preview_id=original['preview_id']), (200, original))
        status, result = self.env.send(original, 'U', 'A')
        self.assertEqual((status, result['actual_lamp'], result['cue']['text']), (200, 'alpha', '吸气'))

    def test_beats_above_sqlite_integer_range_stay_exact(self):
        score = sample()['score']
        score['cues'][0]['beat'] = 2**80 + 1
        score['cues'][1]['beat'] = 2**80
        preview = self.env.prepare(score)
        self.assertEqual([(cue['source']['cue_id'], cue['beat']) for cue in preview['cues']],
                         [('C', 8), ('B', 2**80), ('A', 2**80 + 1)])
