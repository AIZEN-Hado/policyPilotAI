ALTER TABLE events ADD COLUMN review_revision TEXT;

CREATE INDEX events_case_review_revision ON events(case_id, review_revision)
WHERE review_revision IS NOT NULL;

UPDATE documents SET pages=NULL WHERE pages IS NOT NULL AND case_id IN (
    SELECT id FROM cases WHERE state='draft'
);
