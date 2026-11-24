CREATE TABLE cases (
 id UUID PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'draft' CHECK(state IN ('draft','queued','processing','ready','failed')),
 result JSONB, error TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE documents (
 id UUID PRIMARY KEY, case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
 filename TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('policy','schedule','endorsement','bill','discharge','receipt','other')),
 sha256 TEXT NOT NULL, bytes BIGINT NOT NULL, pages JSONB,
 UNIQUE(case_id, sha256)
);
CREATE TABLE events (
 id BIGSERIAL PRIMARY KEY, case_id UUID REFERENCES cases(id) ON DELETE CASCADE,
 action TEXT NOT NULL, actor TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX cases_queue ON cases(state,created_at);
CREATE INDEX documents_case ON documents(case_id);
