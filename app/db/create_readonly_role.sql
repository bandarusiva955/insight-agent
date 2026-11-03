-- Read-only role for running AI-generated SQL.
--
-- Safe to run more than once (idempotent). Nothing is hardcoded: the database
-- name is taken from the connection, and the password is passed in on the
-- command line so it never lives in this file or in git.
--
-- Run as the database owner, after loading the Olist data. Use a password
-- with letters and digits only.
--
-- Windows PowerShell (from the project root):
--   Get-Content app/db/create_readonly_role.sql | docker exec -i insightagent-db psql -U <POSTGRES_USER> -d <POSTGRES_DB> -v ro_password=YourStrongPassword123
-- macOS / Linux:
--   docker exec -i insightagent-db psql -U <POSTGRES_USER> -d <POSTGRES_DB> -v ro_password=YourStrongPassword123 < app/db/create_readonly_role.sql
--
-- Then set in .env:
--   POSTGRES_READONLY_USER=insightagent_ro
--   POSTGRES_READONLY_PASSWORD=YourStrongPassword123

\set ON_ERROR_STOP on

\if :{?ro_password}
\else
  \echo 'ERROR: pass the password with  -v ro_password=YourStrongPassword123'
  \quit
\endif

-- Create the role if it does not exist yet.
SELECT 'CREATE ROLE insightagent_ro LOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'insightagent_ro')
\gexec

-- Always (re)set the password and the safety settings.
SELECT format('ALTER ROLE insightagent_ro LOGIN PASSWORD %L', :'ro_password')
\gexec

ALTER ROLE insightagent_ro SET default_transaction_read_only = on;
ALTER ROLE insightagent_ro SET statement_timeout = '10s';

-- Connect to whichever database this script is running in.
SELECT format('GRANT CONNECT ON DATABASE %I TO insightagent_ro', current_database())
\gexec

-- Business tables only. The app_meta schema (audit log) is deliberately not
-- granted, so this role cannot read it.
GRANT USAGE ON SCHEMA public TO insightagent_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO insightagent_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO insightagent_ro;

\echo 'insightagent_ro is ready (read-only, 10s statement timeout).'
