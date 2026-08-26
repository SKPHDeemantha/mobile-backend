-- =============================================================================
--  Least-privilege application roles.
--
--  Run this AFTER 00_schema.sql, over the DIRECT (non-pooled) Neon endpoint,
--  connected as the Neon-issued owner role for the project.
--
--  Two roles are created:
--    app_api   — used by the running FastAPI service (pooled connection).
--                Can read/write transactional data and call the matching /
--                summary functions, but cannot alter the knowledge base
--                structure or grant roles.
--    app_admin — used only by the SQLAdmin panel. Everything app_api can do,
--                plus full curation rights over the knowledge base and the
--                ability to manage user roles.
--
--  Neither role is the Neon project owner. The owner role's credentials
--  should never be placed in an application .env file or Render/Railway
--  environment variable.
--
--  IMPORTANT: replace the two placeholder passwords below before running
--  this file, then store the real passwords in a password manager — they
--  are not recoverable from Postgres afterwards, only resettable.
-- =============================================================================

CREATE ROLE app_api  WITH LOGIN PASSWORD 'REPLACE_WITH_A_GENERATED_SECRET';
CREATE ROLE app_admin WITH LOGIN PASSWORD 'REPLACE_WITH_A_DIFFERENT_GENERATED_SECRET';

-- Both roles need to see the schemas at all before per-table grants apply.
GRANT USAGE ON SCHEMA kb, app, audit TO app_api, app_admin;

-- ---------------------------------------------------------------------------
--  app_api — transactional read/write, curated-content read-only
-- ---------------------------------------------------------------------------

-- Full CRUD on every transactional table the API owns.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO app_api;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA app TO app_api;

-- Read-only over the curated knowledge base ...
GRANT SELECT ON ALL TABLES IN SCHEMA kb TO app_api;

-- ... except the two tables the API writes to as a side effect of normal
-- traffic: the unrecognised-term growth loop, and embedding backfills.
GRANT INSERT, UPDATE ON kb.unrecognised_terms   TO app_api;
GRANT INSERT, UPDATE ON kb.ingredient_embeddings TO app_api;

-- The matching cascade and the aggregated scan summary are the only ways
-- app_api is allowed to touch matching logic — it never reimplements it.
GRANT EXECUTE ON FUNCTION kb.fn_match_ingredient(text, vector, real, real, integer) TO app_api;
GRANT EXECUTE ON FUNCTION kb.fn_log_unrecognised_term(text)                          TO app_api;
GRANT EXECUTE ON FUNCTION app.fn_scan_summary(uuid, varchar)                          TO app_api;

-- The audit trigger inserts as the invoking role; app_api needs INSERT here
-- even though it never selects from it directly.
GRANT INSERT ON audit.kb_change_log TO app_api;

-- ---------------------------------------------------------------------------
--  app_admin — everything app_api has, plus knowledge-base curation
-- ---------------------------------------------------------------------------

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO app_admin;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA app TO app_admin;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA kb TO app_admin;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA kb TO app_admin;

GRANT EXECUTE ON FUNCTION kb.fn_match_ingredient(text, vector, real, real, integer) TO app_admin;
GRANT EXECUTE ON FUNCTION kb.fn_log_unrecognised_term(text)                          TO app_admin;
GRANT EXECUTE ON FUNCTION app.fn_scan_summary(uuid, varchar)                          TO app_admin;

GRANT SELECT, INSERT ON audit.kb_change_log TO app_admin;

-- Newly created objects (e.g. from a future migration file) should inherit
-- these same grants automatically, so nobody has to remember to re-grant.
ALTER DEFAULT PRIVILEGES IN SCHEMA app FOR ROLE CURRENT_USER
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_api, app_admin;
ALTER DEFAULT PRIVILEGES IN SCHEMA kb FOR ROLE CURRENT_USER
    GRANT SELECT ON TABLES TO app_api;
ALTER DEFAULT PRIVILEGES IN SCHEMA kb FOR ROLE CURRENT_USER
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_admin;
