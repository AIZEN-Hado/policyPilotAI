CREATE TABLE review_snapshots (
 case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
 evidence_revision TEXT NOT NULL,
 result JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY (case_id, evidence_revision)
);
CREATE TABLE review_corrections (
 id UUID PRIMARY KEY,
 case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
 evidence_revision TEXT NOT NULL,
 review_revision TEXT NOT NULL,
 field TEXT NOT NULL,
 value TEXT NOT NULL,
 reason TEXT NOT NULL,
 document_id UUID NOT NULL,
 page INTEGER NOT NULL,
 start_offset INTEGER NOT NULL,
 end_offset INTEGER NOT NULL,
 source_text TEXT NOT NULL,
 source TEXT NOT NULL CHECK(source IN ('rules','neural')),
 outcome TEXT NOT NULL CHECK(outcome IN ('accepted','corrected','no_prediction')),
 previous_suggestions JSONB NOT NULL,
 actor TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 FOREIGN KEY (case_id,evidence_revision) REFERENCES review_snapshots(case_id,evidence_revision) ON DELETE CASCADE
);
CREATE INDEX review_corrections_case ON review_corrections(case_id,created_at);
