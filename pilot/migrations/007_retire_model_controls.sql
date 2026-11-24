-- Retire the removed compute controller without erasing its accounting/history.
-- This records local intent only; provider shutdown/deletion is verified separately.
UPDATE model_control SET enabled=false,phase='retired',generation=generation+1,updated_at=now() WHERE id=1;
INSERT INTO events(case_id,action,actor)
VALUES(NULL,'retired_compute_controls','deployment-migration');
