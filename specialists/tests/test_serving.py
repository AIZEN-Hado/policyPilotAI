"""Inference transport/loader verification without installing a neural runtime."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pilot import specialist_client as client
from specialists.serving import load_checkpoint, windows
from specialists.artifacts import write_manifest, package_directory

DIGEST = 'a' * 64
DOCS = [{'id': 'd1', 'kind': 'policy', 'filename': 'policy.pdf',
         'pages': [{'page': 1, 'text': 'Policy ID: AB-123'}]}]
ENV = {'SPECIALIST_URL': 'http://127.0.0.1:8091', 'SPECIALIST_TOKEN': 'secret-test-token',
       'SPECIALIST_CHECKPOINT_SHA256': DIGEST}


def prediction():
    value = client.result('ready', '', DIGEST)
    item = dict(document_id='d1', filename='policy.pdf', page=1, start_offset=11,
                end_offset=17, source_text='AB-123', value='AB-123', review_reasons=[])
    value['suggestions']['POLICY_ID'] = [item]
    value['evidence']['POLICY_ID'] = [{**item, 'score': 0.3}]
    return value


class TransportTests(unittest.TestCase):
    def review(self, response):
        with patch.dict('os.environ', ENV, clear=True), patch.object(client, '_transport', return_value=response):
            return client.review_specialists(copy.deepcopy(DOCS))

    def test_disabled_does_not_transport(self):
        with patch.dict('os.environ', {}, clear=True), patch.object(client, '_transport') as transport:
            self.assertEqual(client.review_specialists(DOCS)['state'], 'disabled')
            transport.assert_not_called()

    def test_valid_response_deduplicates_coordinates(self):
        response = prediction()
        response['suggestions']['POLICY_ID'] *= 2
        actual = self.review(response)
        self.assertEqual(actual['state'], 'ready')
        self.assertEqual(len(actual['suggestions']['POLICY_ID']), 1)
        self.assertEqual(actual['checkpoint'], DIGEST)

    def test_invalid_outputs_fail_closed(self):
        for field, value in [('document_id', 'another-case'), ('page', True), ('page', 2),
                             ('start_offset', -1), ('end_offset', 100), ('filename', 'wrong.pdf'),
                             ('source_text', 'invented'), ('value', 'invented')]:
            with self.subTest(field=field):
                response = prediction()
                response['suggestions']['POLICY_ID'][0][field] = value
                self.assertEqual(self.review(response)['state'], 'unavailable')
        for score in (float('nan'), float('inf'), True, '0.2'):
            response = prediction()
            response['evidence']['POLICY_ID'][0]['score'] = score
            self.assertEqual(self.review(response)['state'], 'unavailable')
        response = prediction()
        response['checkpoint'] = 'b' * 64
        self.assertEqual(self.review(response)['state'], 'unavailable')
        response = prediction()
        response['suggestions']['UNKNOWN'] = []
        self.assertEqual(self.review(response)['state'], 'unavailable')

    def test_timeout_retains_no_predictions_or_sensitive_errors(self):
        with patch.dict('os.environ', ENV, clear=True), patch.object(client, '_transport', side_effect=TimeoutError('SECRET')):
            response = client.review_specialists(DOCS)
        self.assertEqual(response['state'], 'unavailable')
        self.assertNotIn('SECRET', json.dumps(response))
        self.assertFalse(any(response['suggestions'].values()))

    def test_configuration_and_bounds(self):
        for url in ('http://external.example', 'https://user:password@example.com', 'https://example.com?token=x'):
            with patch.dict('os.environ', {**ENV, 'SPECIALIST_URL': url}, clear=True):
                self.assertEqual(client.specialist_status()['state'], 'unavailable')
        docs = copy.deepcopy(DOCS)
        docs[0]['pages'][0]['text'] = 'a' * (client.MAX_TEXT + 1)
        with self.assertRaises(ValueError):
            client.prepare_documents(docs)

    def test_unsupported_kinds_explicit(self):
        docs = copy.deepcopy(DOCS)
        docs.append({**docs[0], 'id': 'e1', 'kind': 'endorsement'})
        submitted, skipped = client.prepare_documents(docs)
        self.assertTrue(skipped)
        self.assertEqual(len(submitted), 1)

    def test_windows_preserve_source_and_overlap(self):
        docs = copy.deepcopy(DOCS)
        text = ' '.join('word' + str(i) for i in range(700))
        docs[0]['pages'][0]['text'] = text
        chunks = windows(docs, 256)
        self.assertEqual(chunks[0][2], 0)
        self.assertEqual(chunks[-1][3], len(text))
        self.assertLess(chunks[1][2], chunks[0][3])
        for doc, page, start, end in chunks:
            self.assertEqual(page['text'][start:end], text[start:end])


class LoaderTests(unittest.TestCase):
    def test_bad_digest_before_runtime_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.tar.gz'
            path.write_bytes(b'not weights')
            with self.assertRaisesRegex(ValueError, 'fingerprint'):
                load_checkpoint(path, DIGEST)

    def test_source_bundle_is_not_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'source'
            root.mkdir()
            (root / 'code.py').write_text('pass')
            write_manifest(root)
            archive = Path(tmp) / 'source.tar.gz'
            package_directory(root, archive)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, 'missing trained'):
                load_checkpoint(archive, digest)

    def test_incompatible_config_rejected_before_torch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'weights'
            root.mkdir()
            config = json.loads(Path('specialists/config.json').read_text())
            config['generative_model'] = True
            (root / 'metadata.json').write_text(json.dumps({'config': config}))
            for name in ('span.pt', 'rank.pt', 'validation.json', 'reload.json'):
                (root / name).write_text('{}')
            write_manifest(root)
            archive = Path(tmp) / 'weights.tar.gz'
            package_directory(root, archive)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, 'configuration'):
                load_checkpoint(archive, digest)


if __name__ == '__main__':
    unittest.main()
