from pathlib import Path
from .db import connect
with connect() as conn:
    conn.execute('CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())')
    conn.execute('SELECT pg_advisory_xact_lock(519824)')
    for path in sorted((Path(__file__).parent/'migrations').glob('*.sql')):
        if not conn.execute('SELECT 1 FROM schema_migrations WHERE version=%s',(path.name,)).fetchone():
            conn.execute(path.read_text())
            conn.execute('INSERT INTO schema_migrations(version) VALUES(%s)',(path.name,))
print('Migrations applied')
