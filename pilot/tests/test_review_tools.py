"""Immutable field review outcomes, source validation, and safe review exports."""
from datetime import UTC, datetime
import json
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from pilot.review_tools import checklist, evidence_revision, metrics, timeline
from pilot.tests.test_pdf_review import API_AVAILABLE, ReviewDatabase, ReviewRows


class ProjectionTests(unittest.TestCase):
    def test_checklist_and_ambiguous_conflicting_dates(self):
        items = checklist([{'kind': 'bill'}])
        self.assertTrue(next(i for i in items if i['kind'] == 'bill')['present'])
        self.assertFalse(next(i for i in items if i['kind'] == 'receipt')['required'])
        result = {'review_fields': {'fields': {
            'ADMISSION_DATE': {'candidates': [{'value': '2026-11-20'}, {'value': '03/04/2026'}]},
            'DISCHARGE_DATE': {'candidates': [{'value': '2026-11-19'}]}}}}
        entries, warnings = timeline(result, [])
        self.assertEqual(entries[-1]['unresolved_reason'], 'ambiguous_numeric_date')
        self.assertEqual(warnings, ['discharge_before_admission'])
        self.assertEqual(len(entries), 3)

    def test_empty_metrics_are_not_accuracy(self):
        result = metrics([], [])
        self.assertIsNone(result['correction_rate'])
        self.assertIsNone(result['neural']['correction_rate'])
        self.assertEqual(result['by_checkpoint'], [])

    def test_metrics_latest_per_field_snapshot_and_checkpoint(self):
        snapshots = [{'case_id': 'a', 'evidence_revision': 's1', 'result': {'specialists': {'checkpoint': 'cp1'}}},
                     {'case_id': 'a', 'evidence_revision': 's2', 'result': {'specialists': {'checkpoint': 'cp2'}}}]
        base = {'case_id': 'a', 'field': 'POLICY_ID', 'source': 'neural'}
        corrections = [{**base, 'evidence_revision': 's1', 'outcome': outcome} for outcome in ('accepted', 'corrected')]
        corrections.append({**base, 'evidence_revision': 's2', 'outcome': 'accepted'})
        result = metrics(snapshots, corrections)
        self.assertEqual(result['reviewed_fields'], 2)
        self.assertEqual(result['neural']['correction_rate'], .5)
        self.assertEqual([r['checkpoint'] for r in result['by_checkpoint']], ['cp1', 'cp2'])


class ToolDatabase(ReviewDatabase):
    def execute(self, statement, arguments=()):
        rows = super().execute(statement, arguments)
        if rows is None:
            return None
        class ToolRows(ReviewRows):
            @staticmethod
            def convert(row):
                values = ReviewRows.convert(row)
                for key in ('previous_suggestions',):
                    if isinstance(values.get(key), str):
                        values[key] = json.loads(values[key])
                return values
        return ToolRows(rows.cursor)


@unittest.skipUnless(API_AVAILABLE, 'Requires API dependencies')
class ReviewToolRouteTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from pilot.review_routes import register_review_routes
        from pilot.review_tools import record_review_snapshot
        env = patch.dict(os.environ, {'DATABASE_URL': 'postgresql://unused', 'PROXY_TOKEN': 't' * 64,
                                      'APP_ORIGIN': 'https://pilot.example.invalid'})
        env.start()
        self.addCleanup(env.stop)
        from pilot import api
        self.api = api
        self.db = ToolDatabase()
        self.addCleanup(self.db.sql.close)
        self.cid, self.did = str(uuid4()), str(uuid4())
        self.text = 'Policy number: DEMO-1 <script>alert(1)</script>'
        candidate = {'value': 'DEMO-1', 'source_text': 'DEMO-1', 'document_id': self.did,
                     'filename': 'demo.pdf', 'page': 1, 'start_offset': 15, 'end_offset': 21}
        self.result = {'review_fields': {'fields': {'POLICY_ID': {'candidates': [candidate]}}},
                       'specialists': {'state': 'ready', 'checkpoint': 'verified-test',
                                       'suggestions': {'POLICY_ID': [candidate]}}}
        self.docs = [{'id': self.did, 'filename': 'demo.pdf', 'kind': 'schedule', 'sha256': 'abc',
                      'pages': [{'page': 1, 'text': self.text}]}]
        self.db.sql.execute('INSERT INTO cases(id,title,description,state,result) VALUES(?,?,?,?,?)',
                            (self.cid, '<script>title</script>', 'synthetic test', 'ready', json.dumps(self.result)))
        self.db.sql.execute('INSERT INTO documents(id,case_id,filename,kind,sha256,bytes,pages) VALUES(?,?,?,?,?,?,?)',
                            (self.did, self.cid, 'demo.pdf', 'schedule', 'abc', 1, json.dumps(self.docs[0]['pages'])))
        with self.db.connect() as conn:
            record_review_snapshot(conn, self.cid, self.result, self.docs)
        app = FastAPI()
        register_review_routes(app, self.db.connect, api.get_case, lambda request: 'reviewer', api.review_revision, api.event)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.path = '/api/cases/' + self.cid

    def tools(self):
        response = self.client.get(self.path + '/tools')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def body(self, **changes):
        return {'review_revision': self.tools()['review_revision'], 'field': 'POLICY_ID', 'value': 'DEMO-1',
                'reason': 'Checked original', 'document_id': self.did, 'page': 1, 'start_offset': 15,
                'end_offset': 21, 'source': 'neural', **changes}

    def test_edit_invalidates_ack_and_preserves_snapshot(self):
        before = self.tools()
        with self.db.connect() as conn:
            conn.execute('INSERT INTO events(case_id,action,actor,review_revision) VALUES(%s,%s,%s,%s)',
                         (self.cid, 'ack', 'reviewer', before['review_revision']))
        body = self.body()
        response = self.client.post(self.path + '/corrections', json=body)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['outcome'], 'accepted')
        after = self.tools()
        self.assertNotEqual(after['review_revision'], before['review_revision'])
        self.assertEqual(after['evidence_revision'], before['evidence_revision'])
        self.assertEqual(self.client.post(self.path + '/corrections', json=body).status_code, 409)
        self.assertEqual(self.client.post(self.path + '/corrections', json=self.body(value='DEMO-2')).status_code, 201)
        after = self.tools()
        self.assertEqual(len(after['corrections']), 2)
        self.assertEqual(len(after['current_corrections']), 1)
        self.assertEqual(after['current_corrections'][0]['value'], 'DEMO-2')
        stats = self.client.get('/api/review-metrics').json()
        self.assertEqual(stats['neural']['reviewed_fields'], 1)
        self.assertEqual(stats['neural']['corrected'], 1)
        report = self.client.get(self.path + '/report')
        self.assertIn('Acknowledged: False', report.text)

    def test_citation_validation_case_isolation_and_no_neural_prediction(self):
        for changes in ({'document_id': str(uuid4())}, {'end_offset': 999}, {'start_offset': 21},
                        {'page': 2}, {'reason': ' '}, {'field': 'UNKNOWN'}, {'field': 'MEMBER_ID'},
                        {'start_offset': True}):
            response = self.client.post(self.path + '/corrections', json=self.body(**changes))
            self.assertEqual(response.status_code, 422, (changes, response.text))
        self.assertEqual(self.client.get('/api/cases/' + str(uuid4()) + '/tools').status_code, 404)
        self.assertEqual(self.tools()['corrections'], [])

    def test_new_upload_isolates_history_and_delete_cascades(self):
        self.assertEqual(self.client.post(self.path + '/corrections', json=self.body()).status_code, 201)
        with self.db.connect() as conn:
            conn.execute("UPDATE cases SET state='draft',result=NULL,updated_at=now() WHERE id=%s", (self.cid,))
        projected = self.tools()
        self.assertEqual(projected['current_corrections'], [])
        self.assertEqual(len(projected['corrections']), 1)
        with self.db.connect() as conn:
            conn.execute('UPDATE cases SET state=%s,result=%s WHERE id=%s', ('ready', json.dumps(self.result), self.cid))
            conn.execute('UPDATE documents SET sha256=%s WHERE id=%s', ('changed', self.did))
        self.assertEqual(self.tools()['current_corrections'], [])
        with self.db.connect() as conn:
            conn.execute('DELETE FROM cases WHERE id=%s', (self.cid,))
        self.assertEqual(self.client.get('/api/review-metrics').json()['reviewed_fields'], 0)
        self.assertEqual(self.db.sql.execute('SELECT COUNT(*) FROM review_snapshots').fetchone()[0], 0)

    def test_report_escapes_text_and_has_scoped_original_links(self):
        self.client.post(self.path + '/corrections', json=self.body(reason='<img src=x onerror=alert(1)>'))
        response = self.client.get(self.path + '/report')
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment;', response.headers['content-disposition'])
        self.assertNotIn('<script>', response.text)
        self.assertNotIn('<img', response.text)
        self.assertIn('&lt;script&gt;title', response.text)
        self.assertIn(self.path + '/documents/' + self.did, response.text)
        self.assertIn('not ground-truth accuracy', response.text)
