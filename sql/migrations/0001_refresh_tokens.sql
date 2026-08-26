-- =============================================================================
--  Migration 0001 — refresh token revocation table.
--
--  00_schema.sql has no concept of a refresh token: access tokens alone
--  would be fine as pure stateless JWTs, but a refresh token that can never
--  be revoked (on logout, or if a device is lost) is a real security gap.
--  This table is the minimal state needed to revoke one.
--
--  Apply with: python scripts/apply_sql.py sql/migrations/0001_refresh_tokens.sql
--  (direct endpoint; append-only — never edit an already-applied migration).
-- =============================================================================

CREATE TABLE IF NOT EXISTS app.refresh_tokens (
    token_id    uuid        PRIMARY KEY,               -- the JWT's own 'jti' claim
    user_id     uuid        NOT NULL REFERENCES app.users(user_id) ON DELETE CASCADE,
    issued_at   timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,
    revoked_at  timestamptz,
    replaced_by uuid        REFERENCES app.refresh_tokens(token_id) ON DELETE SET NULL
);

COMMENT ON TABLE app.refresh_tokens
    IS 'Tracks issued refresh tokens so they can be individually revoked (logout, rotation, compromised device) without invalidating every session.';

CREATE INDEX IF NOT EXISTS ix_refresh_tokens_user
    ON app.refresh_tokens (user_id)
    WHERE revoked_at IS NULL;

-- Housekeeping: expired/revoked rows are safe to purge periodically.
CREATE INDEX IF NOT EXISTS ix_refresh_tokens_expired
    ON app.refresh_tokens (expires_at)
    WHERE revoked_at IS NULL;
