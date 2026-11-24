"""Exercise archive custody and R2 read-back with a local S3 double."""

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from specialists.artifacts import package_directory, write_manifest
from specialists.backup import REQUIRED_MEMBERS, approved_archive, publish


class AlreadyExists(Exception):
    response = {'ResponseMetadata': {'HTTPStatusCode': 412}}


class BackupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.run = root / ('run-' + 'a' * 32)
        self.run.mkdir()
        for name in REQUIRED_MEMBERS:
            (self.run / name).write_text('synthetic artifact test bytes\n')
        write_manifest(self.run, metadata={'kind': 'remote_specialist_run', 'trained': True})
        self.archive = self.run.with_suffix('.tar.gz')
        self.fingerprint = package_directory(self.run, self.archive)
        self.receipt = self.run.with_suffix('.receipt.json')
        self.receipt.write_text(json.dumps({
            'stage': 'train', 'completed': True, 'archive_verified': True,
            'artifact': self.archive.name, 'artifact_sha256': self.fingerprint['sha256'],
        }))

    def test_matching_run_only(self):
        self.assertEqual(approved_archive(self.archive), self.fingerprint)
        self.receipt.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'matching completed training receipt'):
            approved_archive(self.archive)

    def test_conditional_upload_and_readback(self):
        client = Mock()
        payload = self.archive.read_bytes()
        stream = io.BytesIO(payload)

        def put(**options):
            self.assertEqual(options['IfNoneMatch'], '*')
            self.assertEqual(options['Body'].read(), payload)

        client.put_object.side_effect = put
        client.get_object.return_value = {'ContentLength': len(payload), 'Body': stream}
        result = publish(client, 'model-fixture', self.archive, self.fingerprint)
        self.assertTrue(result['r2_readback_verified'])
        self.assertTrue(stream.closed)
        client.get_object.assert_called_once_with(Bucket='model-fixture', Key=result['key'])

    def test_existing_object_reused_only_when_bytes_match(self):
        client = Mock()
        client.put_object.side_effect = AlreadyExists()
        payload = self.archive.read_bytes()
        client.get_object.return_value = {'ContentLength': len(payload), 'Body': io.BytesIO(payload)}
        self.assertTrue(publish(client, 'model-fixture', self.archive, self.fingerprint)['r2_readback_verified'])
        wrong = bytes([payload[0] ^ 1]) + payload[1:]
        stream = io.BytesIO(wrong)
        client.get_object.return_value = {'ContentLength': len(wrong), 'Body': stream}
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            publish(client, 'model-fixture', self.archive, self.fingerprint)
        self.assertTrue(stream.closed)
