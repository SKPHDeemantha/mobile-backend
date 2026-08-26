# FoodLence backend

FastAPI + Neon Postgres backend for the FoodLence AI food label scanner
(SE5104 mini project, Group 14). Companion to `../mobile-frontend` (Flutter).

- **API**: FastAPI, mounted under `/api/v1`.
- **Database**: Postgres 16 on [Neon](https://neon.tech), schema in `sql/`.
- **Admin panel**: [SQLAdmin](https://aminalaee.dev/sqladmin/), mounted at `/admin` in the same app.
- **Matching logic** (exact / alias / fuzzy / semantic) lives **in the database** as SQL functions — the API calls through to `kb.fn_match_ingredient` and `app.fn_scan_summary` rather than reimplementing that logic in Python. See `sql/00_schema.sql` SECTION 9 for why.

## 1. Neon setup (do this once)

You already have a Neon account; the project itself doesn't exist yet.

1. Go to [console.neon.tech](https://console.neon.tech) → **New Project** → name it `foodlence` → pick the region closest to your users → Postgres 16.
2. On the project dashboard, copy **both** connection strings:
   - **Direct** (the host does *not* end in `-pooler`) — used only for schema changes and the offline scripts below.
   - **Pooled** (the host *does* end in `-pooler`) — used by the running API. Neon's pooled endpoint runs PgBouncer in transaction-pooling mode; the code already accounts for this (`statement_cache_size=0` in `app/core/db.py`).
3. Apply the schema, over the **direct** endpoint:
   ```bash
   pip install asyncpg
   export DATABASE_URL_DIRECT="<paste the DIRECT connection string, in the form postgresql+asyncpg://...>"
   python scripts/apply_sql.py sql/00_schema.sql
   python scripts/apply_sql.py sql/01_roles_and_grants.sql   # see step 4 first!
   python scripts/apply_sql.py sql/migrations/0001_refresh_tokens.sql
   ```
4. **Before** running `01_roles_and_grants.sql`, open it and replace the two placeholder passwords with real generated secrets:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
   Run it once, save the value as `app_api`'s password; run it again for `app_admin`. **Store both passwords in a password manager now** — Postgres never lets you read a password back out.
5. Build your three connection URLs for `.env` by taking the pooled/direct strings from step 2 and swapping in the `app_api` / `app_admin` username and password (never the Neon-issued owner role — that account should never appear in an `.env` file or a hosting provider's dashboard):
   - `DATABASE_URL` = pooled endpoint, `app_api` credentials
   - `DATABASE_URL_DIRECT` = direct endpoint, `app_api` credentials
   - `ADMIN_DATABASE_URL` = pooled endpoint, `app_admin` credentials
6. Sanity check:
   ```bash
   psql "postgresql://app_api:...@...-pooler.../foodlence?sslmode=require" -c "select count(*) from kb.ingredients;"
   # -> 5 (the demo rows baked into 00_schema.sql)
   ```

## 2. Local development

```bash
cp .env.example .env      # fill in the three DATABASE_URL* values from step 1,
                           # and generate JWT_SECRET / ADMIN_SESSION_SECRET / MAINTENANCE_API_KEY
python -m venv .venv && . .venv/Scripts/activate   # or source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://localhost:8000/docs for interactive API docs, or http://localhost:8000/admin for the admin panel (see §5).

To run against a disposable local Postgres instead of Neon (handy while iterating, avoids burning Neon compute hours):

```bash
docker compose up -d postgres
export DATABASE_URL=postgresql+asyncpg://foodlence:foodlence@localhost:5432/foodlence
export DATABASE_URL_DIRECT=$DATABASE_URL
export ADMIN_DATABASE_URL=$DATABASE_URL
python scripts/apply_sql.py sql/00_schema.sql sql/migrations/0001_refresh_tokens.sql
# (skip sql/01_roles_and_grants.sql locally — one shared role is fine for a throwaway container)
uvicorn app.main:app --reload
```

## 3. Loading knowledge base content

```bash
export DATABASE_URL_DIRECT=...   # the direct endpoint
python scripts/seed_knowledge_base.py
```

`scripts/seed_data/ingredients.csv` ships with ~40 common allergen sources and additives — enough to exercise every stage of the matching cascade, but nowhere near the proposal's 500+ entry commitment (§9.1). Growing that CSV (or adding more files and passing them as extra arguments to the script) is ongoing content work, not a one-time setup step. The script is idempotent — re-running it updates existing rows rather than duplicating them.

## 4. Why not Alembic

The schema (`sql/00_schema.sql`) is hand-authored SQL with heavy trigger and function logic — the safety-critical `is_profile_match` flag, the matching cascade, the audit trail. Alembic's autogenerate diffs a Python ORM model against the database and would either miss all of that logic or fight it. Instead:

- `sql/00_schema.sql` is the baseline, applied once.
- Future changes are new, numbered files under `sql/migrations/` (see `0001_refresh_tokens.sql` for the pattern) — **append-only**, never edit a file that's already been applied anywhere real.
- Apply them with `python scripts/apply_sql.py sql/migrations/000N_description.sql` against the direct endpoint.

## 5. Admin panel

`/admin` is protected by its own session-cookie login (`app/admin/auth_backend.py`) — separate from the mobile app's JWT flow, and it connects using the `app_admin` database role (see §1), never the Neon owner role. Log in with any account that has the `ADMIN` role in `app.user_roles`.

New accounts only ever get the `USER` role automatically (`app/api/v1/auth.py`, `/auth/register`). To make the first admin, grant the role directly once:

```sql
INSERT INTO app.user_roles (user_id, role_id)
SELECT u.user_id, r.role_id
FROM app.users u, app.roles r
WHERE u.email = 'you@example.com' AND r.code = 'ADMIN';
```

The most useful view is **Review queue** (`kb.unrecognised_terms`) — every ingredient string the matcher couldn't resolve during a real scan lands there, ranked by how often it's been seen, for you to map to an existing ingredient or add as a new one via the **Ingredients** view.

## 6. Email (verification / password reset)

Uses Gmail SMTP + an App Password — zero cost, no domain required:

1. Turn on 2-Step Verification on the Gmail account you want to send from.
2. Google Account → Security → **App passwords** → generate one for "Mail".
3. Set in `.env`: `MAIL_USERNAME` (the Gmail address), `MAIL_PASSWORD` (the app password, not your normal password), `MAIL_FROM` (same address), `MAIL_SERVER=smtp.gmail.com`, `MAIL_PORT=587`.

If `MAIL_USERNAME` is left blank, the API still works — it just logs the verification/reset code instead of emailing it (see `app/services/mail.py`), which is convenient for local testing.

## 7. Turning on semantic matching

`ENABLE_SEMANTIC_MATCH=false` by default. Stage 4 of `kb.fn_match_ingredient` (vector/semantic similarity) needs a 384-dim embedding computed at request time with `sentence-transformers` (`all-MiniLM-L6-v2`), which pulls in `torch` — a real RAM risk on a free-tier host. Stages 1–3 (exact / curated alias / trigram fuzzy) already cover the large majority of real-world OCR text.

To turn it on once hosting can handle it:

```bash
pip install sentence-transformers   # excluded from the base Docker image, see Dockerfile ARG INSTALL_SEMANTIC
export DATABASE_URL_DIRECT=...
python scripts/generate_embeddings.py     # backfills kb.ingredient_embeddings
# then set ENABLE_SEMANTIC_MATCH=true wherever the API runs, and rebuild the
# Docker image with --build-arg INSTALL_SEMANTIC=1
```

## 8. Hosting (Render)

1. Push this repo to its own GitHub repository (e.g. `foodlence-backend`).
2. [Render](https://render.com) → New → Web Service → connect the repo → Docker runtime.
3. Environment variables: everything in `.env.example`, with real values (the three Neon URLs from §1, `JWT_SECRET`, `ADMIN_SESSION_SECRET`, `MAIL_*`, `CORS_ORIGINS` set to wherever the Flutter app / admin browser will be, `MAINTENANCE_API_KEY`, `ENABLE_SEMANTIC_MATCH=false` to start).
4. Health check path: `/health`.
5. Because Neon's `pg_cron` can only schedule jobs from its `postgres` database (see `sql/00_schema.sql` SECTION 12) and this project's database isn't named that, the periodic `REFRESH MATERIALIZED VIEW CONCURRENTLY kb.mv_allergen_lookup` job runs from GitHub Actions instead (`.github/workflows/ci.yml`, the `refresh-knowledge-base-lookup` job) — set the `API_BASE_URL` and `MAINTENANCE_API_KEY` repo secrets to match your deployed service.

## 9. Testing

```bash
docker compose up -d postgres
pytest -v
```

CI (`.github/workflows/ci.yml`) runs the same suite against a throwaway `pgvector/pgvector:pg16` container — no live Neon credentials ever touch CI. See `tests/conftest.py` for how the schema gets applied fresh before the test session runs.

## 10. API surface

| Endpoint | Notes |
|---|---|
| `POST /api/v1/auth/register`, `/login`, `/refresh`, `/logout` | JWT access + rotating refresh tokens (`app.refresh_tokens`, migration 0001) |
| `POST /api/v1/auth/verify-email`, `/forgot-password`, `/reset-password` | Stateless signed challenge + emailed 6-digit code, no extra DB table |
| `GET/POST/PATCH/DELETE /api/v1/profiles` | Allergen/additive profiles — accepts a client-generated `profile_id` so a profile created offline in the Flutter app can sync up without ID remapping |
| `POST /api/v1/scans` | Accepts **guest** (no auth) or **authenticated** scans; `user_id`/`profile_id` are nullable by design (`sql/00_schema.sql` `ck_scan_profile_requires_user`) |
| `GET /api/v1/scans`, `/scans/{id}` | Requires auth — a user's own history only |
| `GET /api/v1/search` | Manual ingredient lookup / typeahead |
| `GET/PUT/DELETE /api/v1/favorites` | |
| `GET /api/v1/sync/knowledge-base` | Paginated feed for the Flutter app's offline `kb_cache` (see mobile-frontend integration notes) |
| `POST /api/v1/internal/maintenance/refresh-lookup` | Shared-secret protected, called only by the GitHub Actions cron job |
| `/admin/*` | SQLAdmin, see §5 |

Full interactive docs at `/docs` once the server is running.
