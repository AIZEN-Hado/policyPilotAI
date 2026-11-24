"""Synthetic worker integration with isolated storage/database/model doubles."""
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch


def load_worker():
    """Import under a private package name so optional dependencies stay isolated."""
    name = '_synthetic_worker_fixture'
    package = ModuleType(name)
    package.__path__ = [str(Path(__file__).resolve().parents[1])]

    def module(suffix, **values):
        result = ModuleType(name + '.' + suffix)
        result.__dict__.update(values)
        return result

    modules = {
        name: package,
        name + '.config': module('config', MAX_FILE=10 * 1024 * 1024, MAX_PAGES=20, MODEL='fixture-model'),
        name + '.db': module('db', connect=MagicMock()),
        name + '.storage': module('storage', get_storage=Mock(), materialize=MagicMock()),
        name + '.storage_cleanup': module('storage_cleanup', cleanup_pending=Mock()),
        name + '.inference': module('inference', generate=Mock()),
        'httpx': ModuleType('httpx'),
        'psycopg': ModuleType('psycopg'),
        'psycopg.types': ModuleType('psycopg.types'),
        'psycopg.types.json': ModuleType('psycopg.types.json'),
    }
    modules['psycopg.types.json'].Jsonb = lambda value: value
    with patch.dict(sys.modules, modules):
        return importlib.import_module(name + '.worker')


class WorkerContextTests(unittest.TestCase):
    def setUp(self):
        self.worker = load_worker()
        self.conn = MagicMock()
        self.worker.connect.return_value.__enter__.return_value = self.conn
        self.worker.materialize.return_value.__enter__.return_value = Path('/synthetic/unused.pdf')

    def documents(self):
        rows = [{'id': f'bill-{i}', 'kind': 'bill', 'filename': f'synthetic-bill-{i}.pdf',
                 'bytes': 1, 'sha256': 'unused'} for i in range(10)]
        rows += [{'id': kind, 'kind': kind, 'filename': f'synthetic-{kind}.pdf',
                  'bytes': 1, 'sha256': 'unused'} for kind in ('policy', 'schedule')]
        return rows

    def pages(self):
        bill = 'Synthetic room receipt evidence ' * 60
        pages = [[{'page': 1, 'text': bill, 'method': 'native_text', 'needs_verification': False,
                   'parser_version': 'poppler-tesseract-v2', 'quality_reasons': []}] for _ in range(10)]
        pages += [[{'page': 1, 'text': 'The synthetic policy daily room limit is INR 4,000.00 for this fictional insurance product.',
                    'native_text': 'UNREADABLE NATIVE LAYER', 'method': 'ocr',
                    'needs_verification': True, 'parser_version': 'poppler-tesseract-v2',
                    'quality_reasons': ['native_garbled_text', 'ocr_used']}],
                  [{'page': 1, 'text': 'Synthetic schedule for fixture member; policy room benefit applies.\nSum insured: INR 50,000',
                    'method': 'native_text', 'needs_verification': False,
                    'parser_version': 'poppler-tesseract-v2', 'quality_reasons': []}]]
        return pages

    def test_required_sources_and_warnings_reach_model_and_saved_result(self):
        self.conn.execute.return_value.fetchall.return_value = self.documents()
        self.worker.extract_pdf = Mock(side_effect=self.pages())

        def model(system, encoded, schema):
            payload = json.loads(encoded)
            selected = payload['excerpts']
            self.assertTrue({'policy', 'schedule'}.issubset({e['kind'] for e in selected}))
            self.assertLessEqual(sum(len(e['text']) for e in selected), 12000)
            policy = next(e for e in selected if e['kind'] == 'policy')
            self.assertTrue(policy['needs_verification'])
            self.assertEqual(policy['extraction_method'], 'ocr')
            self.assertIn('ocr_used', policy['quality_reasons'])
            self.assertNotIn('native_text', policy)
            self.assertIn('evidence_coverage', payload)
            return {'summary': 'A fictional room limit needs review.', 'questions': [],
                    'findings': [{'statement': 'The excerpt states a daily room limit.',
                                  'quote': 'daily room limit is INR 4,000.00', 'source_id': policy['id']}]}

        self.worker.generate = Mock(side_effect=model)
        self.worker.process({'id': 'fixture-case', 'description': 'Review room receipt evidence.'})
        self.worker.generate.assert_called_once()
        updates = [call.args for call in self.conn.execute.call_args_list
                   if call.args[0].startswith("UPDATE cases SET state='ready'")]
        self.assertEqual(len(updates), 1)
        result = updates[0][1][0]
        self.assertTrue(result['findings'][0]['needs_verification'])
        self.assertIn('evidence_coverage', result)
        self.assertEqual(result['evidence_budget']['unit'], 'text_characters')
        self.assertFalse(result['evidence_budget']['model_token_budget_verified'])
        self.assertTrue(result['extraction_warnings'])
        insured = result['review_fields']['fields']['SUM_INSURED']
        self.assertEqual(insured['value'], '50000.00')
        self.assertEqual(insured['candidates'][0]['source_text'], 'INR 50,000')
        self.assertEqual(insured['candidates'][0]['document_id'], 'schedule')
        self.assertEqual(result['parser_versions'], ['poppler-tesseract-v2'])
        self.assertTrue(any('original' in q for q in result['questions']))

    def test_missing_required_evidence_never_calls_model(self):
        self.conn.execute.return_value.fetchall.return_value = self.documents()[:1]
        self.worker.extract_pdf = Mock(return_value=self.pages()[0])
        with self.assertRaises(self.worker.ExtractionError):
            self.worker.process({'id': 'fixture-case', 'description': 'Review room evidence.'})
        self.worker.generate.assert_not_called()

    def test_blank_optional_document_is_reported_even_without_chunks(self):
        docs = self.documents()
        self.conn.execute.return_value.fetchall.return_value = [docs[0], docs[-2], docs[-1]]
        pages = self.pages()
        empty = [{'page': 1, 'text': '', 'method': 'ocr', 'needs_verification': True,
                  'quality_reasons': ['ocr_used', 'ocr_insufficient_alphanumeric'],
                  'parser_version': 'poppler-tesseract-v2'}]
        self.worker.extract_pdf = Mock(side_effect=[empty, pages[-2], pages[-1]])

        def model(system, encoded, schema):
            context = json.loads(encoded)
            self.assertEqual(context['evidence_coverage']['unreadable_document_ids'], ['bill-0'])
            return {'summary': 'The fictional bill is unreadable.', 'findings': [],
                    'questions': ['Please provide a clearer bill.']}

        self.worker.generate = Mock(side_effect=model)
        self.worker.process({'id': 'fixture-case', 'description': 'Review synthetic documents.'})
        updates = [call.args for call in self.conn.execute.call_args_list
                   if call.args[0].startswith("UPDATE cases SET state='ready'")]
        result = updates[0][1][0]
        self.assertTrue(any('no readable extracted text' in q for q in result['questions']))
        self.assertEqual(result['status'], 'REQUIRES_MORE_INFO')

    def test_punctuation_only_required_document_never_calls_model(self):
        docs = self.documents()
        for kind in ('policy', 'schedule'):
            with self.subTest(kind=kind):
                self.conn.execute.return_value.fetchall.return_value = [next(d for d in docs if d['kind'] == kind)]
                self.worker.extract_pdf = Mock(return_value=[{'page': 1, 'text': '_' * 100,
                    'method': 'ocr', 'needs_verification': True,
                    'quality_reasons': ['ocr_used', 'ocr_insufficient_alphanumeric']}])
                with self.assertRaises(self.worker.ExtractionError):
                    self.worker.process({'id': 'fixture-case', 'description': 'Review synthetic documents.'})
                self.worker.generate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
