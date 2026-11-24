from contextlib import contextmanager
import unittest
from unittest.mock import Mock,patch
import uuid

from pilot.storage_cleanup import cleanup_pending,cleanup_tick


class CleanupTests(unittest.TestCase):
    def run_cleanup(self, referenced=False, failure=False):
        did=uuid.uuid4(); conn=Mock(); storage=Mock()
        rows=iter([{'document_id':did}, {'exists':1} if referenced else None, None])
        statements=[]
        def execute(sql, params=None):
            statements.append(sql)
            result=Mock()
            if sql.startswith('SELECT'):
                result.fetchone.return_value=next(rows)
            return result
        conn.execute.side_effect=execute
        @contextmanager
        def connect():
            yield conn
        if failure:
            storage.delete.side_effect=OSError('storage offline')
        cleanup_pending(connect,storage)
        return did,storage,statements

    def test_deleted_object_removed_then_queue_acknowledged(self):
        did,storage,sql=self.run_cleanup()
        storage.delete.assert_called_once_with(did)
        self.assertTrue(any(s.startswith('DELETE FROM storage_cleanup') for s in sql))

    def test_committed_document_never_deleted(self):
        _,storage,sql=self.run_cleanup(referenced=True)
        storage.delete.assert_not_called()
        self.assertTrue(any(s.startswith('DELETE FROM storage_cleanup') for s in sql))

    def test_failed_removal_retained_and_delayed(self):
        _,storage,sql=self.run_cleanup(failure=True)
        storage.delete.assert_called_once()
        self.assertTrue(any(s.startswith('UPDATE storage_cleanup') for s in sql))
        self.assertFalse(any(s.startswith('DELETE FROM storage_cleanup') for s in sql))

    def test_invalid_batch_never_touches_storage(self):
        for size in (0,21,True):
            with self.assertRaises(ValueError):cleanup_pending(Mock(),Mock(),batch_size=size)

    def test_activity_tick_is_bounded_and_outage_is_contained(self):
        with patch('pilot.storage_cleanup.cleanup_pending',side_effect=OSError('private-provider-detail')) as cleanup:
            cleanup_tick()
            cleanup.assert_called_once_with(batch_size=1)
