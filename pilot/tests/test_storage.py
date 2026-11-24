import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import uuid

from pilot.storage import LocalStorage, S3Storage, materialize, key, r2_endpoint


class StorageTests(unittest.TestCase):
    def test_r2_endpoint_rejects_arbitrary_hosts(self):
        self.assertEqual(r2_endpoint('a'*32), 'https://'+'a'*32+'.r2.cloudflarestorage.com')
        for value in ['https://example.com', '../secret', 'a'*31, 'a'*32+'@evil.test']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                r2_endpoint(value)

    def test_r2_omits_unsupported_aws_encryption_header(self):
        client=Mock()
        S3Storage(client,'bucket',aws_encryption=False).put(self.did,self.source)
        self.assertNotIn('ServerSideEncryption',client.put_object.call_args.kwargs)
        self.assertNotIn('ACL',client.put_object.call_args.kwargs)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.did = uuid.uuid4()
        self.data = b'%PDF-1.4 synthetic document bytes'
        self.source = self.root / 'source.pdf'
        self.source.write_bytes(self.data)
        self.sha = hashlib.sha256(self.data).hexdigest()

    def test_local_round_trip_and_idempotent_delete(self):
        storage = LocalStorage(self.root / 'objects')
        storage.put(self.did, self.source)
        self.assertEqual((storage.root/key(self.did)).stat().st_mode & 0o777, 0o600)
        with materialize(storage,self.did,len(self.data),self.sha,100) as path:
            self.assertEqual(path.read_bytes(),self.data)
        self.assertFalse(path.exists())
        storage.delete(self.did)
        storage.delete(self.did)
        self.assertFalse((storage.root/key(self.did)).exists())

    def test_cleanup_when_parser_raises(self):
        storage = LocalStorage(self.root / 'objects')
        storage.put(self.did,self.source)
        with self.assertRaises(RuntimeError):
            with materialize(storage,self.did,len(self.data),self.sha,100) as path:
                raise RuntimeError('parser failed')
        self.assertFalse(path.exists())

    def test_wrong_hash_or_size_rejected(self):
        storage = LocalStorage(self.root / 'objects')
        storage.put(self.did,self.source)
        for size, sha in [(len(self.data),'0'*64),(100,self.sha)]:
            with self.subTest(size=size), self.assertRaises(ValueError):
                with materialize(storage,self.did,size,sha,100):
                    self.fail('Corrupt bytes were exposed')

    def test_traversal_rejected(self):
        for value in ['../../secret','/tmp/file','name.pdf','']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                key(value)

    def test_s3_put_encrypted_without_public_acl_or_filename(self):
        client=Mock(); storage=S3Storage(client,'private-bucket')
        storage.put(self.did,self.source)
        args=client.put_object.call_args.kwargs
        self.assertEqual(args['ServerSideEncryption'],'AES256')
        self.assertEqual(args['Key'],'documents/'+key(self.did))
        self.assertNotIn('ACL',args)

    def test_s3_stream_limit_even_if_metadata_lies(self):
        client=Mock(); body=io.BytesIO(self.data)
        client.get_object.return_value={'ContentLength':1,'Body':body}
        with self.assertRaises(ValueError):
            S3Storage(client,'bucket').read_into(self.did,io.BytesIO(),5)
        self.assertTrue(body.closed)

    def test_s3_large_metadata_rejected_and_body_closed(self):
        client=Mock(); body=io.BytesIO(self.data)
        client.get_object.return_value={'ContentLength':1000,'Body':body}
        with self.assertRaises(ValueError):
            S3Storage(client,'bucket').read_into(self.did,io.BytesIO(),100)
        self.assertTrue(body.closed)

    def test_s3_read_failure_closes_body(self):
        client=Mock(); body=Mock()
        body.read.side_effect=OSError('interrupted')
        client.get_object.return_value={'ContentLength':10,'Body':body}
        with self.assertRaises(OSError):
            S3Storage(client,'bucket').read_into(self.did,io.BytesIO(),100)
        body.close.assert_called_once()

    def test_s3_outage_propagates_for_cleanup_retry(self):
        client=Mock(); client.delete_object.side_effect=OSError('unavailable')
        with self.assertRaises(OSError):
            S3Storage(client,'bucket').delete(self.did)

    def test_local_download_size_bound(self):
        storage=LocalStorage(self.root/'objects'); storage.put(self.did,self.source)
        with self.assertRaises(ValueError):
            storage.read_into(self.did,io.BytesIO(),1)
