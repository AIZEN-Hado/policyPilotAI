import copy
import json
import unittest
from pilot.core import coverage_report, make_chunks, select_evidence, validate_output

class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.e=[{'id':'a:p1:c0','document_id':'a','filename':'wording.pdf','kind':'policy','page':1,'text':'The daily room limit is INR 4,000.00 for this policy.'}]
        self.good={'summary':'Check room benefit.','findings':[{'statement':'The excerpt states a daily room limit.','quote':'daily room limit is INR 4,000.00','source_id':'a:p1:c0'}],'questions':[]}
    def test_valid_citation_has_source(self):
        result=validate_output(self.good,self.e)
        self.assertEqual(result['findings'][0]['document_id'],'a')
        self.assertEqual(result['status'],'REVIEW_REQUIRED')
    def test_unknown_source_rejected(self):
        self.good['findings'][0]['source_id']='other-claim'
        with self.assertRaises(ValueError):validate_output(self.good,self.e)
    def test_invented_quote_rejected(self):
        self.good['findings'][0]['quote']='The daily limit is INR 9,000.00'
        with self.assertRaises(ValueError):validate_output(self.good,self.e)
    def test_missing_evidence_abstains(self):
        self.good['findings']=[]
        self.assertEqual(validate_output(self.good,[])['status'],'REQUIRES_MORE_INFO')
    def test_truncated_context_warns(self):
        self.assertTrue(validate_output(self.good,self.e,True)['questions'])
    def test_non_object_rejected(self):
        with self.assertRaises(ValueError):validate_output([],self.e)
    def test_bad_questions_rejected(self):
        self.good['questions']=['ok',42]
        with self.assertRaises(ValueError):validate_output(self.good,self.e)
    def test_selection_preserves_document_coverage(self):
        chunks=self.e+[dict(self.e[0],id='b:p1:c0',document_id='b',text='A receipt without search terms.')]
        selected,truncated=select_evidence(chunks,'daily room',limit=1000)
        self.assertEqual({x['document_id'] for x in selected},{'a','b'})
        self.assertFalse(truncated)
    def test_budget_signals_partial_context(self):
        selected,truncated=select_evidence(self.e,'room',limit=5)
        self.assertEqual(selected,[]);self.assertTrue(truncated)
    def test_chunk_page_provenance(self):
        chunks=make_chunks([{'id':'a','filename':'bill.pdf','kind':'bill','pages':[{'page':2,'text':'x'*2400}]}])
        self.assertEqual(len(chunks),3);self.assertTrue(all(c['page']==2 for c in chunks))

    def test_twelve_document_case_keeps_late_policy_and_schedule(self):
        chunks = [dict(self.e[0], id=f'b{i}:p1:c0', document_id=f'b{i}',
                       kind='bill', text='room charge ' + 'x' * 1088) for i in range(10)]
        chunks += [dict(self.e[0], text='Policy waiting period ' + 'x' * 1078),
                   dict(self.e[0], id='s:p1:c0', document_id='s', kind='schedule',
                        text='Schedule sum insured ' + 'x' * 1079)]
        selected, truncated = select_evidence(chunks, 'room charge', limit=2200)
        self.assertEqual({c['kind'] for c in selected}, {'policy', 'schedule'})
        self.assertTrue(truncated)
        self.assertLessEqual(sum(len(c['text']) for c in selected), 2200)
        report = coverage_report(chunks, selected)
        self.assertEqual(report['omitted_document_ids'], [f'b{i}' for i in range(10)])
        self.assertEqual(report['missing_kinds'], ['bill'])
        self.assertEqual(report['total_chunks'], 12)
        self.assertEqual(report['selected_chunks'], 2)
        self.assertFalse(report['complete'])
        json.dumps(report)

    def test_endorsement_has_priority_over_relevant_bill(self):
        chunks = [dict(self.e[0], id='b:p1:c0', document_id='b', kind='bill',
                       text='Daily room charges are printed on this bill.'),
                  dict(self.e[0], id='e:p1:c0', document_id='e', kind='endorsement',
                       text='The endorsement effective date requires verification.')]
        selected, truncated = select_evidence(chunks, 'daily room', limit=60)
        self.assertEqual([c['kind'] for c in selected], ['endorsement'])
        self.assertTrue(truncated)

    def test_policy_relevance_precedes_short_footer_when_budget_suffices(self):
        chunks = [dict(self.e[0], id='a:p1:c0', text='Footer'),
                  dict(self.e[0], id='a:p2:c0', page=2,
                       text='The relevant waiting period is thirty days.'),
                  dict(self.e[0], id='s:p1:c0', document_id='s', kind='schedule',
                       text='Sum insured is one million rupees.')]
        selected, _ = select_evidence(chunks, 'waiting period', limit=100)
        self.assertEqual(selected[0]['id'], 'a:p2:c0')
        self.assertIn('schedule', {c['kind'] for c in selected})

    def test_policy_selection_reserves_space_for_schedule(self):
        chunks = [dict(self.e[0], id='a:p1:c0', text='waiting period ' + 'x' * 85),
                  dict(self.e[0], id='a:p2:c0', page=2, text='Policy ' + 'x' * 13),
                  dict(self.e[0], id='s:p1:c0', document_id='s', kind='schedule',
                       text='Schedule ' + 'x' * 21)]
        selected, _ = select_evidence(chunks, 'waiting period', limit=50)
        self.assertEqual([c['id'] for c in selected], ['a:p2:c0', 's:p1:c0'])

    def test_character_budget_counts_unicode_characters_not_utf8_bytes(self):
        text = 'बीमा राशि सीमा'
        chunks = [dict(self.e[0], text=text)]
        selected, truncated = select_evidence(chunks, 'बीमा', limit=len(text))
        self.assertEqual(selected, chunks)
        self.assertFalse(truncated)
        selected, truncated = select_evidence(chunks, 'बीमा', limit=len(text) - 1)
        self.assertEqual(selected, [])
        self.assertTrue(truncated)
        for invalid in (-1, 2.5, True):
            with self.subTest(limit=invalid), self.assertRaises(ValueError):
                select_evidence(chunks, 'बीमा', limit=invalid)

    def test_unicode_search_normalization_keeps_original_text(self):
        chunks = [dict(self.e[0], id='a:p1:c0', text='Irrelevant policy text.'),
                  dict(self.e[0], id='a:p2:c0', page=2, text='ＲＯＯＭ बीमा limit applies.')]
        selected, _ = select_evidence(chunks, 'room बीमा', limit=30)
        self.assertEqual(selected[0]['id'], 'a:p2:c0')
        self.assertEqual(selected[0]['text'], 'ＲＯＯＭ बीमा limit applies.')
        reversed_selected, _ = select_evidence(list(reversed(chunks)), 'room बीमा', limit=30)
        self.assertEqual(selected, reversed_selected)

    def test_clause_and_exception_remain_verbatim_across_old_slice_boundary(self):
        prefix = 'Background provision. ' * 48
        clause = ('The room benefit is limited to INR 4,000 per day. '
                  'Except for ICU treatment, which follows the separate ICU limit.')
        text = '  ' + prefix + '\n\n' + clause + '\n'
        chunks = make_chunks([{'id': 'a', 'filename': 'policy.pdf', 'kind': 'policy',
                               'pages': [{'page': 7, 'text': text}]}])
        self.assertTrue(any(clause in c['text'] for c in chunks))
        for chunk in chunks:
            self.assertEqual(text[chunk['start_offset']:chunk['end_offset']], chunk['text'])
            self.assertLessEqual(len(chunk['text']), 1200)
            self.assertEqual(chunk['page'], 7)
        self.assertEqual(chunks, make_chunks([{'id': 'a', 'filename': 'policy.pdf',
                                             'kind': 'policy', 'pages': [{'page': 7, 'text': text}]}]))

    def test_overlong_table_splits_at_rows_with_verbatim_offsets(self):
        rows = [f'Room category {i:02d} | INR {i + 1000} | ' + ' '.join(['included'] * 8) for i in range(30)]
        text = '\n'.join(rows)
        chunks = make_chunks([{'id': 'a', 'filename': 'schedule.pdf', 'kind': 'schedule',
                               'pages': [{'page': 1, 'text': text}]}])
        self.assertGreater(len(chunks), 1)
        for row in rows:
            self.assertTrue(any(row in c['text'] for c in chunks), row)
        for chunk in chunks:
            self.assertEqual(text[chunk['start_offset']:chunk['end_offset']], chunk['text'])
            self.assertLessEqual(len(chunk['text']), 1200)

    def test_unbroken_fallback_retains_overlap_and_offsets(self):
        text = '  ' + 'x' * 2400 + '  '
        chunks = make_chunks([{'id': 'a', 'filename': 'bill.pdf', 'kind': 'bill',
                               'pages': [{'page': 1, 'text': text}]}])
        self.assertEqual([(c['start_offset'], c['end_offset']) for c in chunks],
                         [(2, 1202), (1052, 2252), (2102, 2402)])
        self.assertEqual(chunks[0]['text'][-150:], chunks[1]['text'][:150])

    def test_page_metadata_survives_chunk_and_citation(self):
        text = '  The daily room limit is INR 4,000.00 for this policy.  '
        page = {'page': 2, 'text': text, 'method': 'native_text',
                'needs_verification': True, 'quality_reasons': ['native_replacement_characters'],
                'parser_version': 'poppler-tesseract-v2'}
        chunks = make_chunks([{'id': 'a', 'filename': 'policy.pdf', 'kind': 'policy',
                               'pages': [page]}])
        good = copy.deepcopy(self.good)
        good['findings'][0]['source_id'] = chunks[0]['id']
        finding = validate_output(good, chunks)['findings'][0]
        self.assertEqual(finding['extraction_method'], 'native_text')
        self.assertTrue(finding['needs_verification'])
        self.assertEqual(finding['quality_reasons'], ['native_replacement_characters'])
        self.assertEqual(finding['parser_version'], 'poppler-tesseract-v2')
        self.assertEqual(text[finding['quote_start_offset']:finding['quote_end_offset']],
                         finding['quote'])
        self.assertNotIn('native_text', chunks[0])
        self.assertNotIn('parser_version', self.e[0])

    def test_coverage_distinguishes_partial_document_from_omitted_document(self):
        chunks = self.e + [dict(self.e[0], id='a:p2:c0', page=2),
                           dict(self.e[0], id='s:p1:c0', document_id='s', kind='schedule')]
        report = coverage_report(chunks, self.e)
        self.assertEqual(report['partially_selected_document_ids'], ['a'])
        self.assertEqual(report['omitted_document_ids'], ['s'])
        self.assertEqual(report['missing_kinds'], ['schedule'])
        self.assertEqual(report['coverage_basis'], 'supplied_extracted_chunks_only')
        self.assertFalse(report['complete'])
        self.assertTrue(coverage_report(chunks, chunks)['complete'])

    def test_neighbors_include_clause_exception_when_space_remains(self):
        chunks = [dict(self.e[0], id='a:p1:c0', start_offset=0,
                       text='The room benefit applies to eligible hospital stays.'),
                  dict(self.e[0], id='a:p1:c1', start_offset=100,
                       text='Exception: ICU limits are defined separately.'),
                  dict(self.e[0], id='a:p1:c2', start_offset=200,
                       text='Additional room benefit details with many room terms.')]
        selected, _ = select_evidence(chunks, 'room benefit eligible', limit=100)
        self.assertEqual([c['id'] for c in selected], ['a:p1:c0', 'a:p1:c1'])

    def test_malformed_source_identifiers_raise_value_error(self):
        for invalid in ([], {}, None, 42, True, ['a:p1:c0']):
            good = copy.deepcopy(self.good)
            good['findings'][0]['source_id'] = invalid
            with self.subTest(source_id=invalid), self.assertRaises(ValueError):
                validate_output(good, self.e)

    def test_required_exact_response_and_finding_keys(self):
        for key in ('summary', 'questions', 'findings'):
            malformed = copy.deepcopy(self.good)
            del malformed[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                validate_output(malformed, self.e)
        malformed = dict(self.good, payout=4000)
        with self.assertRaises(ValueError):
            validate_output(malformed, self.e)
        for key in ('statement', 'quote', 'source_id'):
            malformed = copy.deepcopy(self.good)
            del malformed['findings'][0][key]
            with self.subTest(missing_finding=key), self.assertRaises(ValueError):
                validate_output(malformed, self.e)
        malformed = copy.deepcopy(self.good)
        malformed['findings'][0]['confidence'] = 1
        with self.assertRaises(ValueError):
            validate_output(malformed, self.e)

    def test_response_field_types_are_enforced(self):
        for key, invalid in (('summary', 3), ('summary', ''), ('findings', {}),
                             ('questions', 'missing')):
            malformed = dict(self.good, **{key: invalid})
            with self.subTest(field=key, value=invalid), self.assertRaises(ValueError):
                validate_output(malformed, self.e)
        for key, invalid in (('statement', []), ('quote', []), ('statement', '')):
            malformed = copy.deepcopy(self.good)
            malformed['findings'][0][key] = invalid
            with self.subTest(finding=key, value=invalid), self.assertRaises(ValueError):
                validate_output(malformed, self.e)

    def test_quote_requires_literal_whitespace_and_unicode(self):
        source = dict(self.e[0], text='The daily  room limit is INR 4,000.00.')
        with self.assertRaises(ValueError):
            validate_output(self.good, [source])
        good = copy.deepcopy(self.good)
        good['findings'][0]['quote'] = 'daily  room limit is INR 4,000.00'
        self.assertEqual(validate_output(good, [source])['status'], 'REVIEW_REQUIRED')
        source['text'] = 'The daily room limit is INR ４,０００.００.'
        with self.assertRaises(ValueError):
            validate_output(self.good, [source])

if __name__=='__main__':unittest.main()
