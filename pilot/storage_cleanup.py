"""Durable, idempotent cleanup of abandoned uploads and deleted-case objects."""
from .storage import get_storage


def cleanup_pending(connect_fn=None, storage=None, batch_size=20):
    if type(batch_size) is not int or not 1<=batch_size<=20:
        raise ValueError('Cleanup batch must be between 1 and 20')
    if connect_fn is None:
        from .db import connect
        connect_fn = connect
    if storage is None:
        storage = get_storage()
    # Bound each pass; failed deletes remain queued. No sensitive error logging.
    stats={'removed':0,'retained':0,'failed':0}
    for _ in range(batch_size):
        with connect_fn() as conn:
            row = conn.execute('SELECT document_id FROM storage_cleanup WHERE eligible_at<=now() '
                               'ORDER BY eligible_at FOR UPDATE SKIP LOCKED LIMIT 1').fetchone()
            if not row:
                return stats
            did = row['document_id']
            referenced = conn.execute('SELECT 1 FROM documents WHERE id=%s', (did,)).fetchone()
            if not referenced:
                try:
                    storage.delete(did)
                    stats['removed']+=1
                except Exception:
                    stats['failed']+=1
                    conn.execute("UPDATE storage_cleanup SET eligible_at=now()+interval '5 minutes' "
                                 'WHERE document_id=%s', (did,))
                    continue
            else:
                stats['retained']+=1
            conn.execute('DELETE FROM storage_cleanup WHERE document_id=%s', (did,))
    return stats


def cleanup_tick():
    """One best-effort attempt per app activity; durable intent survives interruption."""
    try:
        cleanup_pending(batch_size=1)
    except Exception:
        # No credentials, signed URLs or provider exception text in logs. The
        # unchanged queue is inspected through the operator's maintenance view.
        pass
