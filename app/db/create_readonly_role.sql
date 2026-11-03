-- Read-only role for running AI-generated SQL.
--
-- Run once as the database owner, after loading the Olist data.
-- Windows PowerShell (from the project root):
--   Get-Content app/db/create_readonly_role.sql | docker exec -i insightagent-db psql -U <POSTGRES_USER> -d <POSTGRES_DB>
-- macOS / Linux:
--   docker exec -i insightagent-db psql -U <POSTGRES_USER> -d <POSTGRES_DB> < app/db/create_readonly_role.sql
--
-- Before running: replace CHANGE_ME with a strong password, and replace
-- insightagent below if your POSTGRES_DB has a different name.
--
-- Then set POSTGRES_READONLY_USER=insightagent_ro and
-- POSTGRES_READONLY_PASSWORD in .env (see .env.example).

CREATE ROLE insightagent_ro LOGIN PASSWORD 'CHANGE_ME';

GRANT CONNECT ON DATABASE insightagent TO insightagent_ro;
GRANT USAGE ON SCHEMA public TO insightagent_ro;

-- Business tables only. app_meta (audit log) is deliberately not granted.
GRANT SELECT ON ALL TABLES IN SCHEMA public TO insightagent_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO insightagent_ro;

-- Defence in depth: even if something slips past the validator, this role
-- cannot write and cannot run long queries.
ALTER ROLE insightagent_ro SET default_transaction_read_only = on;
ALTER ROLE insightagent_ro SET statement_timeout = '10s';

REVOKE ALL ON SCHEMA app_meta FROM insightagent_ro;
