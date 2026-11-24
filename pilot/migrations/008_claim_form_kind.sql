ALTER TABLE documents DROP CONSTRAINT documents_kind_check;
ALTER TABLE documents ADD CONSTRAINT documents_kind_check
    CHECK (kind IN ('policy','schedule','endorsement','claim_form','bill','discharge','receipt','other'));
