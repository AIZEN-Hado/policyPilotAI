CREATE TABLE pilot_sessions (
    token_hash TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    credential_hash TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX pilot_sessions_expiry ON pilot_sessions(expires_at);
CREATE TABLE pilot_login_guard (
    id INTEGER PRIMARY KEY CHECK (id=1),
    attempts INTEGER NOT NULL DEFAULT 0,
    window_started TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO pilot_login_guard(id) VALUES(1);
