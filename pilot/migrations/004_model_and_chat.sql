CREATE TABLE model_control (
 id INTEGER PRIMARY KEY CHECK(id=1), enabled BOOLEAN NOT NULL DEFAULT false,
 phase TEXT NOT NULL DEFAULT 'off', generation BIGINT NOT NULL DEFAULT 0,
 started_at TIMESTAMPTZ, warmup_job TEXT, model_revision TEXT,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO model_control(id) VALUES(1);
CREATE TABLE model_jobs (
 id UUID PRIMARY KEY, provider_id TEXT, generation BIGINT NOT NULL,
 kind TEXT NOT NULL, case_id UUID REFERENCES cases(id) ON DELETE SET NULL,
 snapshot TEXT, payload JSONB NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
 result JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX model_jobs_active ON model_jobs(state);
CREATE TABLE case_messages (
 id BIGSERIAL PRIMARY KEY, case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
 question TEXT NOT NULL, snapshot TEXT NOT NULL, response JSONB,
 state TEXT NOT NULL DEFAULT 'pending', job_id UUID REFERENCES model_jobs(id) ON DELETE SET NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
