-- Initial DB owner retains schema privileges, but not cluster-wide superuser power.
-- Docker entrypoint executes this on a NEW database volume only.
ALTER ROLE pilot NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
