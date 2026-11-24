"""Run PDF review through HTTP with local storage and self-contained PDFs."""
from contextlib import contextmanager
from datetime import UTC, datetime
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID

from pilot.storage import LocalStorage

API_AVAILABLE = all(importlib.util.find_spec(name) for name in ('fastapi', 'httpx', 'psycopg'))
FILLER = 'Fictional test evidence for the hospitalization of the listed member.'


def synthetic_pdf(*page_lines):
    """Build a small PDF. An empty list creates a page with an image and no text."""
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    pages = []
    for lines in page_lines:
        page_id = len(objects) + 1
        pages.append(f'{page_id} 0 R')
        objects.append((f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] '
                        f'/Resources << /Font << /F1 3 0 R >> >> /Contents {page_id + 1} 0 R >>').encode())
        if lines:
            text = ' Tj T* '.join(f'({line})' for line in lines)
            stream = f'BT /F1 12 Tf 18 TL 72 720 Td {text} Tj ET'.encode()
        else:
            stream = b'q 200 0 0 200 72 400 cm BI /W 1 /H 1 /CS /G /BPC 8 ID \x80 EI Q'
        objects.append(f'<< /Length {len(stream)} >>\nstream\n'.encode() + stream + b'\nendstream')
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(pages)}] /Count {len(pages)} >>".encode()
    pdf = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf.extend(f'{number} 0 obj\n'.encode() + obj + b'\nendobj\n')
    xref = len(pdf)
    pdf.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:
        pdf.extend(f'{offset:010d} 00000 n \n'.encode())
    pdf.extend(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    return bytes(pdf)


class ReviewDatabase:
    """Use SQLite for route SQL and rollback checks, with PostgreSQL value adapters."""

    def __init__(self):
        self.sql = sqlite3.connect(':memory:', check_same_thread=False)
        self.sql.row_factory = sqlite3.Row
        self.sql.create_function('now', 0, lambda: datetime.now(UTC).isoformat())
        self.sql.executescript('''
            PRAGMA foreign_keys=ON;
            CREATE TABLE cases (id TEXT PRIMARY KEY, title TEXT, description TEXT,
                state TEXT DEFAULT 'draft', result TEXT, error TEXT, updated_at TEXT DEFAULT (now()));
            CREATE TABLE documents (id TEXT PRIMARY KEY, case_id TEXT REFERENCES cases(id) ON DELETE CASCADE,
                filename TEXT, kind TEXT, sha256 TEXT, bytes INTEGER, pages TEXT, UNIQUE(case_id, sha256));
            CREATE TABLE events (id INTEGER PRIMARY KEY, case_id TEXT REFERENCES cases(id) ON DELETE CASCADE,
                action TEXT, actor TEXT, created_at TEXT DEFAULT (now()));
            CREATE TABLE storage_cleanup (document_id TEXT PRIMARY KEY, eligible_at TEXT);
        ''')
        migration = Path(__file__).resolve().parents[1] / 'migrations' / '009_review_revision.sql'
        self.sql.executescript(migration.read_text())
        migration = migration.with_name('010_review_tools.sql')
        # SQLite's timestamp DEFAULT syntax requires parentheses around now().
        self.sql.executescript(migration.read_text().replace('DEFAULT now()', 'DEFAULT (now())'))

    @contextmanager
    def connect(self):
        with self.sql:
            yield self

    def execute(self, statement, arguments=()):
        from psycopg.types.json import Jsonb

        if statement.startswith('SET TRANSACTION'):
            return None
        statement = statement.removesuffix(' FOR UPDATE').replace('%s', '?')
        arguments = tuple(str(value) if isinstance(value, UUID) else
                          json.dumps(value.obj) if isinstance(value, Jsonb) else value for value in arguments)
        return ReviewRows(self.sql.execute(statement, arguments))


class ReviewRows:
    def __init__(self, cursor):
        self.cursor = cursor

    def fetchone(self):
        row = self.cursor.fetchone()
        return self.convert(row) if row is not None else None

    def fetchall(self):
        return [self.convert(row) for row in self.cursor.fetchall()]

    @staticmethod
    def convert(row):
        values = dict(row)
        for key in ('pages', 'result', 'previous_suggestions'):
            if values.get(key) is not None:
                values[key] = json.loads(values[key])
        if 'updated_at' in values:
            values['updated_at'] = datetime.fromisoformat(values['updated_at'])
        return values


@unittest.skipUnless(API_AVAILABLE, 'Requires API dependencies')
class PdfReviewRouteTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'DATABASE_URL': 'postgresql://unused', 'AUTH_MODE': 'proxy',
                                      'PROXY_TOKEN': 't' * 64, 'APP_ORIGIN': 'https://pilot.example.invalid'})
        env.start()
        self.addCleanup(env.stop)
        from fastapi.testclient import TestClient
        from pilot import api

        self.api = api
        self.db = ReviewDatabase()
        self.addCleanup(self.db.sql.close)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        adapters = patch.multiple(api, connect=self.db.connect, get_storage=lambda: LocalStorage(folder.name))
        adapters.start()
        self.addCleanup(adapters.stop)
        settings = patch.multiple(api.config, AUTH_MODE='proxy', PROCESSING_ENABLED=False)
        settings.start()
        self.addCleanup(settings.stop)
        self.client = TestClient(api.app, base_url=api.config.APP_ORIGIN, headers={
            'X-Proxy-Token': api.config.PROXY_TOKEN, 'Origin': api.config.APP_ORIGIN,
        })
        self.addCleanup(self.client.close)

    def case(self):
        response = self.client.post('/api/cases', json={
            'title': 'Synthetic hospitalization', 'description': 'Review fictional dates against the attached evidence.',
        })
        self.assertEqual(response.status_code, 201, response.text)
        return '/api/cases/' + response.json()['id']

    def upload(self, case, kind, name, pdf):
        response = self.client.put(case + '/documents', params={'kind': kind, 'filename': name},
                                   headers={'Content-Type': 'application/pdf'}, content=pdf)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()['id']

    def detail(self, case):
        response = self.client.get(case)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def run_review(self, case):
        response = self.client.post(case + '/pdf-review')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'state': 'ready'})
        return self.detail(case)

    @patch('pilot.pdf_review.ocr_available', return_value=False)
    def test_conflicting_dates_cite_case_scoped_pages_and_image_is_flagged(self, _ocr_available):
        case = self.case()
        other_case = self.case()
        claim = synthetic_pdf([FILLER, 'Admission date: 16 March 2026'])
        discharge = synthetic_pdf([FILLER, 'Admission date: 15 March 2026', 'Discharge date: 19 March 2026'], [])
        claim_id = self.upload(case, 'claim_form', 'claim.pdf', claim)
        discharge_id = self.upload(case, 'discharge', 'discharge.pdf', discharge)
        other_id = self.upload(other_case, 'claim_form', 'unrelated.pdf',
                               synthetic_pdf([FILLER, 'Admission date: 21 March 2026']))

        row = self.run_review(case)
        fields = row['result']['review_fields']['fields']
        self.assertEqual(fields['ADMISSION_DATE']['status'], 'conflicting')
        self.assertIsNone(fields['ADMISSION_DATE']['value'])
        self.assertEqual(fields['DISCHARGE_DATE']['value'], '2026-03-19')
        self.assertEqual(row['result']['total_pages'], 3)
        self.assertEqual(row['result']['ocr_pages'], 0)
        self.assertEqual(row['result']['parser_versions'], ['poppler-native-v1'])
        docs = {document['id']: document for document in row['documents']}
        self.assertEqual(set(docs), {claim_id, discharge_id})
        for field in fields.values():
            for candidate in field['candidates']:
                page = docs[candidate['document_id']]['pages'][candidate['page'] - 1]
                self.assertEqual(page['text'][candidate['start_offset']:candidate['end_offset']],
                                 candidate['source_text'])
        self.assertEqual({c['source_text'] for c in fields['ADMISSION_DATE']['candidates']},
                         {'16 March 2026', '15 March 2026'})
        self.assertEqual(row['result']['extraction_warnings'][0]['document_id'], discharge_id)
        self.assertEqual(row['result']['extraction_warnings'][0]['page'], 2)
        self.assertIn('ocr_unavailable', row['result']['extraction_warnings'][0]['quality_reasons'])
        self.assertEqual(docs[discharge_id]['pages'][1]['text'], '')
        self.assertTrue(docs[discharge_id]['pages'][1]['needs_verification'])
        self.assertEqual(self.client.get(case + '/documents/' + other_id).status_code, 404)
        self.assertEqual(self.client.get(case + '/documents/' + claim_id).content, claim)

    @patch('pilot.pdf_review.ocr_available', return_value=True)
    @patch('pilot.pdf_review.run_review_ocr')
    def test_scanned_page_returns_unverified_field_with_exact_source(self, ocr, _ocr_available):
        case = self.case()
        document = self.upload(case, 'claim_form', 'claim.pdf', synthetic_pdf([FILLER], []))
        ocr.side_effect = ['', FILLER + '\nMember ID: SYN-M123']

        row = self.run_review(case)
        result = row['result']
        self.assertEqual(result['ocr_pages'], 1)
        self.assertEqual(result['parser_versions'], ['poppler-native-v1', 'poppler-tesseract-v2'])
        self.assertEqual([call.args[0][0] for call in ocr.call_args_list], ['pdftoppm', 'tesseract'])
        self.assertEqual(ocr.call_args_list[0].args[0][1:5], ['-f', '2', '-l', '2'])
        page = row['documents'][0]['pages'][1]
        self.assertEqual(page['native_text'], '')
        self.assertEqual(page['method'], 'ocr')
        self.assertTrue(page['needs_verification'])
        self.assertIn('ocr_used', result['extraction_warnings'][0]['quality_reasons'])
        field = result['review_fields']['fields']['MEMBER_ID']
        self.assertEqual(field['status'], 'needs_verification')
        citation, = field['candidates']
        self.assertEqual(citation['document_id'], document)
        self.assertEqual(citation['page'], 2)
        self.assertEqual(page['text'][citation['start_offset']:citation['end_offset']], 'SYN-M123')
        self.assertIn('check_against_original', citation['review_reasons'])

    def test_new_upload_clears_derived_pages_and_requires_new_acknowledgement(self):
        case = self.case()
        self.upload(case, 'claim_form', 'claim.pdf', synthetic_pdf([FILLER, 'Admission date: 16 March 2026']))
        first = self.run_review(case)
        self.assertFalse(first['review_acknowledged'])
        self.assertEqual(self.run_review(case)['review_revision'], first['review_revision'])
        old = {'review_revision': first['review_revision']}
        self.assertEqual(self.client.post(case + '/review').status_code, 409)
        for _ in range(2):
            self.assertEqual(self.client.post(case + '/review', json=old).status_code, 200)
        self.assertTrue(self.detail(case)['review_acknowledged'])

        self.upload(case, 'discharge', 'added.pdf', synthetic_pdf([FILLER, 'Discharge date: 19 March 2026']))
        draft = self.detail(case)
        self.assertEqual(draft['state'], 'draft')
        self.assertIsNone(draft['result'])
        self.assertIsNone(draft['review_revision'])
        self.assertFalse(draft['review_acknowledged'])
        self.assertTrue(all(document['pages'] is None for document in draft['documents']))
        self.assertEqual(self.client.post(case + '/review', json=old).status_code, 409)

        second = self.run_review(case)
        self.assertNotEqual(second['review_revision'], first['review_revision'])
        self.assertFalse(second['review_acknowledged'])
        self.assertEqual(self.client.post(case + '/review', json=old).status_code, 409)
        self.assertEqual(sum(event['action'] == self.api.ACKNOWLEDGEMENT_ACTION for event in second['events']), 1)
        current = {'review_revision': second['review_revision']}
        self.assertEqual(self.client.post(case + '/review', json=current).status_code, 200)
        self.assertTrue(self.detail(case)['review_acknowledged'])

    def test_upload_during_extraction_discards_result_and_can_be_retried(self):
        case = self.case()
        self.upload(case, 'claim_form', 'claim.pdf', synthetic_pdf([FILLER, 'Admission date: 16 March 2026']))
        review_documents = self.api.review_documents

        def upload_before_commit(*args, **kwargs):
            result = review_documents(*args, **kwargs)
            self.upload(case, 'discharge', 'new.pdf', synthetic_pdf([FILLER, 'Discharge date: 19 March 2026']))
            return result

        with patch.object(self.api, 'review_documents', side_effect=upload_before_commit):
            response = self.client.post(case + '/pdf-review')
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn('changed during review', response.json()['detail'])
        row = self.detail(case)
        self.assertEqual(row['state'], 'draft')
        self.assertIsNone(row['result'])
        self.assertTrue(all(document['pages'] is None for document in row['documents']))
        self.assertNotIn('pdf_fields_reviewed', {event['action'] for event in row['events']})
        self.assertEqual(self.run_review(case)['result']['total_pages'], 2)

    def test_timeout_and_database_failure_leave_no_partial_review(self):
        case = self.case()
        self.upload(case, 'claim_form', 'claim.pdf', synthetic_pdf([FILLER, 'Admission date: 16 March 2026']))
        timeout = subprocess.TimeoutExpired('private document path', 15)
        with patch('pilot.pdf_review.subprocess.run', side_effect=timeout):
            response = self.client.post(case + '/pdf-review')
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json(), {'detail': 'PDF review exceeded the time limit.'})
        self.assertIsNone(self.detail(case)['documents'][0]['pages'])

        self.db.sql.executescript('''
            CREATE TRIGGER fail_review BEFORE INSERT ON events WHEN NEW.action='pdf_fields_reviewed'
            BEGIN SELECT RAISE(ABORT, 'private event details'); END;
        ''')
        response = self.client.post(case + '/pdf-review')
        self.assertEqual(response.status_code, 503, response.text)
        self.assertNotIn('private event details', response.text)
        row = self.detail(case)
        self.assertEqual(row['state'], 'draft')
        self.assertIsNone(row['result'])
        self.assertIsNone(row['documents'][0]['pages'])
        self.db.sql.execute('DROP TRIGGER fail_review')
        self.assertEqual(self.run_review(case)['result']['total_pages'], 1)

    def test_page_limit_safe_failure_preserves_original(self):
        case = self.case()
        fixture = synthetic_pdf([FILLER], [])
        document = self.upload(case, 'bill', 'two-pages.pdf', fixture)
        with patch.object(self.api.config, 'MAX_PAGES', 1):
            response = self.client.post(case + '/pdf-review')
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn('1-page limit', response.json()['detail'])
        self.assertIsNone(self.detail(case)['documents'][0]['pages'])
        self.assertEqual(self.client.get(case + '/documents/' + document).content, fixture)
