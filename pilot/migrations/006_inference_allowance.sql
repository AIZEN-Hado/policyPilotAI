-- One demo allowance across every Start/Stop cycle. Reserve compute conservatively
-- and leave USD 0.30 of the user's USD 1 allowance for overhead. Not an invoice.
CREATE TABLE inference_allowance (
 id INTEGER PRIMARY KEY CHECK(id=1),
 compute_reservation_limit_usd NUMERIC(12,6) NOT NULL DEFAULT 0.70,
 compute_reserved_usd NUMERIC(12,6) NOT NULL DEFAULT 0,
 approved_total_usd NUMERIC(12,6) NOT NULL DEFAULT 1.00,
 CHECK(compute_reserved_usd>=0),
 CHECK(compute_reservation_limit_usd>0 AND compute_reservation_limit_usd<=approved_total_usd)
);
INSERT INTO inference_allowance(id) VALUES(1);
ALTER TABLE model_jobs ADD COLUMN reserved_compute_usd NUMERIC(12,6) NOT NULL DEFAULT 0;
