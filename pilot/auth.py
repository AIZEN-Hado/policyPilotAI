"""Shared pilot login: opaque revocable sessions and bounded password hashing."""
import hashlib
import hmac
import re
import secrets

COOKIE = '__Host-policypilot-session'
SESSION_SECONDS = 8 * 60 * 60
HASH_ITERATIONS = 600_000


def password_hash(password):
    if not 16 <= len(password) <= 1024:
        raise ValueError('Use a password between 16 and 1024 characters')
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), HASH_ITERATIONS)
    return f'pbkdf2_sha256${HASH_ITERATIONS}${salt}${digest.hex()}'


def valid_hash(encoded):
    return isinstance(encoded, str) and re.fullmatch(
        r'pbkdf2_sha256\$600000\$[0-9a-f]{32}\$[0-9a-f]{64}', encoded) is not None


def verify_password(password, encoded):
    if not isinstance(password, str) or len(password) > 1024 or not valid_hash(encoded):
        return False
    _, iterations, salt, expected = encoded.split('$')
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(iterations))
    return hmac.compare_digest(digest.hex(), expected)


def session_hash(token):
    if not isinstance(token, str) or re.fullmatch(r'[A-Za-z0-9_-]{43}', token) is None:
        return None
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(token, connect, username, credential_hash):
    digest = session_hash(token)
    if digest is None:
        return None
    with connect() as conn:
        row = conn.execute(
            'SELECT username FROM pilot_sessions WHERE token_hash=%s AND expires_at>now() '
            'AND username=%s AND credential_hash=%s',
            (digest, username, hashlib.sha256(credential_hash.encode()).hexdigest())).fetchone()
    return row['username'] if row else None


def login(username, password, connect, expected_user, credential_hash):
    # One durable account-wide bucket; do not trust forwarded IP headers for limits.
    # A row lock serializes attempts across processes. After five failures, wait
    # until the 15-minute window ends. Lockout also affects legitimate reviewers.
    with connect() as conn:
        guard = conn.execute(
            'SELECT attempts,window_started,window_started <= now()-interval \'15 minutes\' AS expired '
            'FROM pilot_login_guard WHERE id=1 FOR UPDATE').fetchone()
        if not guard:
            raise RuntimeError('Authentication migration missing')
        if guard['expired']:
            conn.execute('UPDATE pilot_login_guard SET attempts=0,window_started=now() WHERE id=1')
        elif guard['attempts'] >= 5:
            return None, 'throttled'
        password_ok = verify_password(password, credential_hash)
        if not (hmac.compare_digest(username.encode(), expected_user.encode()) and password_ok):
            conn.execute('UPDATE pilot_login_guard SET attempts=attempts+1 WHERE id=1')
            return None, 'invalid'
        conn.execute('UPDATE pilot_login_guard SET attempts=0,window_started=now() WHERE id=1')
        conn.execute('DELETE FROM pilot_sessions WHERE expires_at<=now() OR username<>%s OR credential_hash<>%s',
                     (expected_user, hashlib.sha256(credential_hash.encode()).hexdigest()))
        # Bound concurrent sessions for this shared account.
        conn.execute('DELETE FROM pilot_sessions WHERE token_hash IN '
                     '(SELECT token_hash FROM pilot_sessions ORDER BY expires_at DESC OFFSET 19)')
        token = secrets.token_urlsafe(32)
        conn.execute('INSERT INTO pilot_sessions(token_hash,username,credential_hash,expires_at) '
                     "VALUES(%s,%s,%s,now()+interval '8 hours')",
                     (session_hash(token), expected_user, hashlib.sha256(credential_hash.encode()).hexdigest()))
    return token, None


def logout(token, connect):
    digest = session_hash(token)
    if digest is not None:
        with connect() as conn:
            conn.execute('DELETE FROM pilot_sessions WHERE token_hash=%s', (digest,))
