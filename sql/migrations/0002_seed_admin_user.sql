-- =============================================================================
--  Migration 0002 — seed the first admin account.
--
--  New accounts created through POST /api/v1/auth/register only ever get the
--  USER role (app/api/v1/auth.py) — ADMIN can never be self-assigned. The
--  SQLAdmin panel at /admin requires an account that already holds ADMIN, so
--  the very first one has to be granted directly. This migration creates that
--  account and grants it both USER and ADMIN.
--
--  Login (at <deployed-url>/admin):
--      email:    heshandeemantha99@gmail.com
--      password: d-CDD59l8ioEuCKyuIUq
--
--  The password hash below is bcrypt (cost 12), produced exactly the way
--  app/core/security.py hash_password() does. Change the password after first
--  login via the API's password-reset flow, or re-run this migration with a
--  new hash (it is idempotent and updates the hash on conflict).
--
--  Apply with: python scripts/apply_sql.py sql/migrations/0002_seed_admin_user.sql
--  (direct endpoint; append-only — never edit an already-applied migration).
-- =============================================================================

INSERT INTO app.users (email, password_hash, display_name, preferred_language, email_verified_at, is_active)
VALUES (
    'heshandeemantha99@gmail.com',
    '$2b$12$9T./a554GqGJybwQMhtfL.6xTycHl/uTZNh6/Xww3Eeyte..GgqEe',
    'Heshan Deemantha',
    'en',
    now(),          -- pre-verified: no email round-trip needed for this account
    true
)
ON CONFLICT (email) DO UPDATE
    SET password_hash     = EXCLUDED.password_hash,
        is_active         = true,
        email_verified_at = COALESCE(app.users.email_verified_at, now()),
        updated_at        = now();

-- Grant USER + ADMIN. Roles are seeded by 00_schema.sql; look them up by code
-- rather than assuming role_id values.
INSERT INTO app.user_roles (user_id, role_id)
SELECT u.user_id, r.role_id
FROM app.users u
CROSS JOIN app.roles r
WHERE u.email = 'heshandeemantha99@gmail.com'
  AND r.code IN ('USER', 'ADMIN')
ON CONFLICT (user_id, role_id) DO NOTHING;
