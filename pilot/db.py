from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row
from .config import DATABASE_URL

@contextmanager
def connect():
    with psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10) as conn:
        yield conn
