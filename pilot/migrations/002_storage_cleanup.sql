-- Survives upload/DB failures and case deletion; deliberately has no case FK.
CREATE TABLE storage_cleanup (
 document_id UUID PRIMARY KEY,
 eligible_at TIMESTAMPTZ NOT NULL DEFAULT now() + interval '1 hour'
);
