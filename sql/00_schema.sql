-- =============================================================================
--  NutriScan — AI-Powered Packaged Food Allergen & Additive Scanner
--  Database schema for Neon Serverless Postgres (PostgreSQL 16+)
--  Group 08 — Department of Software Engineering, Sabaragamuwa University
--
--  Normal form   : 3NF throughout (see NORMALISATION NOTES at the end)
--  Architecture  : 3 schemas — kb (reference), app (transactional), audit
--  Run order     : this file is idempotent-ish; run top to bottom on a fresh DB
--
--  IMPORTANT (Neon):
--    * Run migrations over the DIRECT endpoint, not the '-pooler' endpoint.
--      DDL and session-level state break under PgBouncer transaction pooling.
--    * Use the pooled endpoint for the FastAPI runtime connection only.
-- =============================================================================


-- =============================================================================
--  SECTION 1 — EXTENSIONS
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS vector;      -- pgvector: semantic ingredient matching
CREATE EXTENSION IF NOT EXISTS pg_trgm;     -- trigram similarity: OCR typo tolerance
CREATE EXTENSION IF NOT EXISTS unaccent;    -- diacritic stripping during normalisation
CREATE EXTENSION IF NOT EXISTS citext;      -- case-insensitive email / ingredient names
CREATE EXTENSION IF NOT EXISTS pgcrypto;    -- gen_random_uuid(), digest() for text hashing
CREATE EXTENSION IF NOT EXISTS btree_gin;   -- composite GIN indexes mixing scalar + trigram

-- Optional. Neon supports pg_cron, but cron.schedule_in_database() is NOT available,
-- so jobs can only be scheduled from the 'postgres' database. If your application
-- database is named something else, schedule refreshes from GitHub Actions instead.
-- CREATE EXTENSION IF NOT EXISTS pg_cron;


-- =============================================================================
--  SECTION 2 — SCHEMAS
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS kb;      -- knowledge base: slow-changing reference data
CREATE SCHEMA IF NOT EXISTS app;     -- transactional: users, profiles, scans
CREATE SCHEMA IF NOT EXISTS audit;   -- append-only change history

COMMENT ON SCHEMA kb    IS 'Curated reference data: ingredients, allergens, additives, aliases, embeddings.';
COMMENT ON SCHEMA app   IS 'Transactional data: user accounts, allergen profiles, scans and match results.';
COMMENT ON SCHEMA audit IS 'Append-only audit trail for knowledge base modifications.';


-- =============================================================================
--  SECTION 3 — ENUMERATED TYPES
--  Used where the value set is a fixed technical vocabulary with no attributes
--  of its own. Where a category carries its own attributes (name, description,
--  icon) a lookup TABLE is used instead — see kb.additive_categories.
-- =============================================================================

CREATE TYPE kb.ingredient_type AS ENUM (
    'allergen_source',   -- e.g. peanut butter, whey powder
    'additive',          -- e.g. E621, sodium benzoate
    'neutral'            -- e.g. water, salt, rice flour
);

CREATE TYPE kb.allergen_certainty AS ENUM (
    'definite',          -- 'peanut oil' -> peanuts
    'probable',          -- 'lecithin'   -> soy (usually soy-derived)
    'possible'           -- 'natural flavouring' -> milk (sometimes)
);

CREATE TYPE kb.term_status AS ENUM (
    'pending',           -- seen in a scan, not yet in the knowledge base
    'mapped',            -- an admin has linked it to an ingredient
    'ignored'            -- noise, not a real ingredient
);

CREATE TYPE app.severity_level AS ENUM ('mild', 'moderate', 'severe');

CREATE TYPE app.match_method AS ENUM (
    'exact',             -- canonical name matched verbatim
    'alias',             -- matched a curated alternative name
    'fuzzy',             -- trigram similarity above threshold (OCR errors)
    'semantic'           -- vector cosine similarity above threshold
);

CREATE TYPE app.scan_status AS ENUM ('pending', 'processing', 'completed', 'failed');

CREATE TYPE app.ocr_engine AS ENUM ('mlkit_ondevice', 'cloud_vision');

CREATE TYPE app.platform AS ENUM ('android', 'ios');


-- =============================================================================
--  SECTION 4 — IMMUTABLE TEXT NORMALISATION FUNCTIONS
--
--  These must be declared IMMUTABLE so they can be used inside GENERATED
--  columns and expression indexes.
--
--  GOTCHA: the single-argument unaccent(text) is only STABLE, because it
--  resolves the dictionary at run time. The two-argument
--  unaccent('unaccent'::regdictionary, text) form pins the dictionary and can
--  legitimately be wrapped as IMMUTABLE. Marking the one-arg form IMMUTABLE
--  is a silent correctness bug that corrupts indexes.
-- =============================================================================

CREATE OR REPLACE FUNCTION kb.immutable_unaccent(p_text text)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
STRICT
AS $$
    SELECT public.unaccent('public.unaccent'::regdictionary, p_text);
$$;

COMMENT ON FUNCTION kb.immutable_unaccent(text)
    IS 'IMMUTABLE wrapper around unaccent() so it can be used in generated columns and expression indexes.';


CREATE OR REPLACE FUNCTION kb.normalise_text(p_text text)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT NULLIF(
        btrim(
            regexp_replace(
                regexp_replace(
                    regexp_replace(
                        lower(kb.immutable_unaccent(COALESCE(p_text, ''))),
                        '\(\s*\d+(\.\d+)?\s*%\s*\)|\d+(\.\d+)?\s*%', ' ', 'g'  -- strip "(12%)" / "12%"
                    ),
                    '[^a-z0-9 ]+', ' ', 'g'                                     -- strip punctuation
                ),
                '\s+', ' ', 'g'                                                 -- collapse whitespace
            )
        ),
    '');
$$;

COMMENT ON FUNCTION kb.normalise_text(text)
    IS 'Canonical text normaliser: lowercase, de-accent, strip percentages and punctuation, collapse whitespace.';


-- Shared trigger function: maintains updated_at on every mutable table.
CREATE OR REPLACE FUNCTION app.fn_set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;


-- =============================================================================
--  SECTION 5 — KNOWLEDGE BASE TABLES (schema: kb)
-- =============================================================================

-- 5.1  Languages ------------------------------------------------------------
CREATE TABLE kb.languages (
    language_code   varchar(5)  PRIMARY KEY,                -- 'en', 'si', 'ta'
    name            varchar(60) NOT NULL UNIQUE,
    native_name     varchar(60) NOT NULL,
    is_active       boolean     NOT NULL DEFAULT true
);

INSERT INTO kb.languages (language_code, name, native_name) VALUES
    ('en', 'English', 'English'),
    ('si', 'Sinhala', 'සිංහල'),
    ('ta', 'Tamil',   'தமிழ்')
ON CONFLICT DO NOTHING;


-- 5.2  Allergen groups ------------------------------------------------------
CREATE TABLE kb.allergen_groups (
    allergen_group_id  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    code               varchar(30) NOT NULL UNIQUE,          -- 'MILK', 'PEANUT'
    is_major           boolean     NOT NULL DEFAULT true,     -- one of the 9 major groups
    icon_code          varchar(50) NOT NULL,
    display_order      smallint    NOT NULL DEFAULT 100,
    is_active          boolean     NOT NULL DEFAULT true,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE kb.allergen_groups
    IS 'The 9 internationally recognised major allergen groups plus common sensitivities. Display names live in kb.allergen_group_translations (3NF).';

INSERT INTO kb.allergen_groups (code, is_major, icon_code, display_order) VALUES
    ('PEANUT',    true,  'peanut',    1),
    ('TREE_NUT',  true,  'tree-nut',  2),
    ('MILK',      true,  'milk',      3),
    ('EGG',       true,  'egg',       4),
    ('SOY',       true,  'soy',       5),
    ('WHEAT',     true,  'wheat',     6),
    ('FISH',      true,  'fish',      7),
    ('SHELLFISH', true,  'shellfish', 8),
    ('SESAME',    true,  'sesame',    9),
    ('GLUTEN',    false, 'gluten',   10),
    ('SULPHITE',  false, 'sulphite', 11),
    ('MUSTARD',   false, 'mustard',  12)
ON CONFLICT DO NOTHING;


-- 5.3  Additive categories --------------------------------------------------
--  Extracted into its own table rather than stored as a string on each
--  additive: the category name and description depend only on the category,
--  not on the additive. Storing them inline is a transitive dependency and
--  therefore a 3NF violation.
CREATE TABLE kb.additive_categories (
    additive_category_id smallserial PRIMARY KEY,
    code                 varchar(40) NOT NULL UNIQUE,
    name                 varchar(80) NOT NULL,
    description          text
);

INSERT INTO kb.additive_categories (code, name, description) VALUES
    ('PRESERVATIVE',     'Preservative',     'Extends shelf life by inhibiting microbial growth.'),
    ('COLOUR',           'Colour',           'Adds or restores colour to a food product.'),
    ('SWEETENER',        'Sweetener',        'Provides sweetness without or with reduced sugar.'),
    ('EMULSIFIER',       'Emulsifier',       'Keeps oil and water phases from separating.'),
    ('STABILISER',       'Stabiliser',       'Maintains physical and chemical structure.'),
    ('FLAVOUR_ENHANCER', 'Flavour enhancer', 'Intensifies existing flavour without adding its own.'),
    ('ANTIOXIDANT',      'Antioxidant',      'Delays oxidation and rancidity.'),
    ('ACIDITY_REGULATOR','Acidity regulator','Controls the acidity or alkalinity of the product.'),
    ('THICKENER',        'Thickener',        'Increases viscosity without altering other properties.'),
    ('RAISING_AGENT',    'Raising agent',    'Releases gas to increase the volume of a dough or batter.')
ON CONFLICT DO NOTHING;


-- 5.4  Ingredients (supertype) ----------------------------------------------
--  A single canonical entity table for everything the matcher can resolve to.
--  Additive-only attributes are pushed down into kb.additive_details (1:1
--  subtype) so this table has no columns that are meaningless for most rows.
CREATE TABLE kb.ingredients (
    ingredient_id    uuid                PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_name   citext              NOT NULL UNIQUE,
    normalised_name  text                GENERATED ALWAYS AS (kb.normalise_text(canonical_name::text)) STORED,
    ingredient_type  kb.ingredient_type  NOT NULL,
    is_active        boolean             NOT NULL DEFAULT true,
    created_at       timestamptz         NOT NULL DEFAULT now(),
    updated_at       timestamptz         NOT NULL DEFAULT now(),

    CONSTRAINT ck_ingredients_name_not_blank CHECK (btrim(canonical_name::text) <> '')
);

COMMENT ON COLUMN kb.ingredients.normalised_name
    IS 'Stored generated column. Guarantees the matcher and the writer normalise identically — impossible to drift.';


-- 5.5  Additive details (1:1 subtype of ingredients) ------------------------
CREATE TABLE kb.additive_details (
    ingredient_id        uuid        PRIMARY KEY
                                     REFERENCES kb.ingredients(ingredient_id) ON DELETE CASCADE,
    e_number             varchar(15) UNIQUE,                 -- 'E621', 'E500ii'
    additive_category_id smallint    NOT NULL
                                     REFERENCES kb.additive_categories(additive_category_id),
    concern_level        smallint    NOT NULL DEFAULT 1,     -- 1 low .. 3 high
    adi_mg_per_kg_bw     numeric(8,3),                       -- acceptable daily intake, where published
    is_permitted_lk      boolean     NOT NULL DEFAULT true,  -- permitted under Sri Lankan food regulations

    CONSTRAINT ck_additive_concern CHECK (concern_level BETWEEN 1 AND 3),
    CONSTRAINT ck_additive_e_number_format CHECK (e_number IS NULL OR e_number ~ '^E[0-9]{3,4}[a-z]{0,3}$')
);

COMMENT ON TABLE kb.additive_details
    IS 'Subtype table. Attributes that exist only for additives are kept out of kb.ingredients to avoid a wide, mostly-NULL parent table.';


-- 5.6  Ingredient to allergen links (M:N) -----------------------------------
--  Genuinely many-to-many: 'lecithin' may be soy- or sunflower-derived;
--  'natural flavouring' can conceal milk, soy or wheat. A single FK on
--  kb.ingredients would lose this and cause false negatives — the most
--  dangerous failure mode in this system.
CREATE TABLE kb.ingredient_allergens (
    ingredient_id     uuid                  NOT NULL
                                            REFERENCES kb.ingredients(ingredient_id) ON DELETE CASCADE,
    allergen_group_id uuid                  NOT NULL
                                            REFERENCES kb.allergen_groups(allergen_group_id) ON DELETE RESTRICT,
    certainty         kb.allergen_certainty NOT NULL DEFAULT 'definite',
    note              text,
    created_at        timestamptz           NOT NULL DEFAULT now(),

    PRIMARY KEY (ingredient_id, allergen_group_id)
);


-- 5.7  Ingredient aliases ---------------------------------------------------
CREATE TABLE kb.ingredient_aliases (
    alias_id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    ingredient_id     uuid        NOT NULL REFERENCES kb.ingredients(ingredient_id) ON DELETE CASCADE,
    alias_text        citext      NOT NULL,
    normalised_alias  text        GENERATED ALWAYS AS (kb.normalise_text(alias_text::text)) STORED,
    language_code     varchar(5)  NOT NULL DEFAULT 'en' REFERENCES kb.languages(language_code),
    is_curated        boolean     NOT NULL DEFAULT true,   -- false = learned from unrecognised terms
    is_active         boolean     NOT NULL DEFAULT true,
    created_at        timestamptz NOT NULL DEFAULT now()
);

-- An alias must resolve to exactly one ingredient, otherwise matching is ambiguous.
CREATE UNIQUE INDEX uq_alias_normalised
    ON kb.ingredient_aliases (normalised_alias, language_code)
    WHERE is_active;


-- 5.8  Ingredient embeddings ------------------------------------------------
--  Held in a separate table rather than as a column on kb.ingredients:
--    (a) a vector(384) adds ~1.5 KB per row, bloating the hot parent table
--        and destroying cache efficiency for sequential and index scans;
--    (b) the embedding depends on (ingredient, model) — not on the ingredient
--        alone — so keeping it inline would break 3NF once a second model or
--        model version is introduced.
CREATE TABLE kb.ingredient_embeddings (
    ingredient_id uuid         NOT NULL REFERENCES kb.ingredients(ingredient_id) ON DELETE CASCADE,
    model_name    varchar(80)  NOT NULL DEFAULT 'all-MiniLM-L6-v2',
    model_version varchar(20)  NOT NULL DEFAULT '1.0',
    embedding     vector(384)  NOT NULL,
    is_stale      boolean      NOT NULL DEFAULT false,
    generated_at  timestamptz  NOT NULL DEFAULT now(),

    PRIMARY KEY (ingredient_id, model_name, model_version)
);


-- 5.9  Translations ---------------------------------------------------------
--  Classic 3NF treatment of multilingual content. Columns such as
--  explanation_si / explanation_ta on kb.ingredients would be a repeating
--  group and would require a schema migration for every new language.
CREATE TABLE kb.ingredient_translations (
    ingredient_id uuid        NOT NULL REFERENCES kb.ingredients(ingredient_id) ON DELETE CASCADE,
    language_code varchar(5)  NOT NULL REFERENCES kb.languages(language_code),
    display_name  varchar(200) NOT NULL,
    explanation   text,
    generated_by  varchar(20) NOT NULL DEFAULT 'llm',       -- 'llm' | 'human'
    model_version varchar(40),
    reviewed_at   timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (ingredient_id, language_code),
    CONSTRAINT ck_translation_source CHECK (generated_by IN ('llm', 'human'))
);

CREATE TABLE kb.allergen_group_translations (
    allergen_group_id uuid         NOT NULL REFERENCES kb.allergen_groups(allergen_group_id) ON DELETE CASCADE,
    language_code     varchar(5)   NOT NULL REFERENCES kb.languages(language_code),
    display_name      varchar(100) NOT NULL,
    description       text,

    PRIMARY KEY (allergen_group_id, language_code)
);


-- 5.10 Unrecognised terms ---------------------------------------------------
--  The knowledge base growth loop. Every ingredient the matcher fails to
--  resolve is recorded here, ranked by frequency, and reviewed by an admin.
CREATE TABLE kb.unrecognised_terms (
    term_id              uuid           PRIMARY KEY DEFAULT gen_random_uuid(),
    normalised_term      text           NOT NULL UNIQUE,
    sample_raw_text      text           NOT NULL,
    occurrence_count     integer        NOT NULL DEFAULT 1,
    status               kb.term_status NOT NULL DEFAULT 'pending',
    resolved_ingredient_id uuid         REFERENCES kb.ingredients(ingredient_id) ON DELETE SET NULL,
    first_seen_at        timestamptz    NOT NULL DEFAULT now(),
    last_seen_at         timestamptz    NOT NULL DEFAULT now(),

    CONSTRAINT ck_term_resolution CHECK (
        (status = 'mapped' AND resolved_ingredient_id IS NOT NULL)
        OR (status <> 'mapped')
    )
);


-- =============================================================================
--  SECTION 6 — APPLICATION TABLES (schema: app)
-- =============================================================================

-- 6.1  Roles and users ------------------------------------------------------
CREATE TABLE app.roles (
    role_id smallserial PRIMARY KEY,
    code    varchar(30) NOT NULL UNIQUE,
    name    varchar(60) NOT NULL
);

INSERT INTO app.roles (code, name) VALUES
    ('USER',  'Registered User'),
    ('ADMIN', 'Administrator')
ON CONFLICT DO NOTHING;

CREATE TABLE app.users (
    user_id           uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    email             citext       NOT NULL UNIQUE,
    password_hash     varchar(255) NOT NULL,
    display_name      varchar(150) NOT NULL,
    -- FK only: storing the language *name* here would be a transitive
    -- dependency on kb.languages and a 3NF violation.
    preferred_language varchar(5)  NOT NULL DEFAULT 'en' REFERENCES kb.languages(language_code),
    email_verified_at timestamptz,
    is_active         boolean      NOT NULL DEFAULT true,
    created_at        timestamptz  NOT NULL DEFAULT now(),
    updated_at        timestamptz  NOT NULL DEFAULT now(),

    CONSTRAINT ck_users_email_format CHECK (email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$')
);

CREATE TABLE app.user_roles (
    user_id     uuid        NOT NULL REFERENCES app.users(user_id) ON DELETE CASCADE,
    role_id     smallint    NOT NULL REFERENCES app.roles(role_id) ON DELETE RESTRICT,
    granted_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, role_id)
);


-- 6.2  Allergen profiles ----------------------------------------------------
CREATE TABLE app.profiles (
    profile_id   uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      uuid         NOT NULL REFERENCES app.users(user_id) ON DELETE CASCADE,
    profile_name varchar(100) NOT NULL,
    is_default   boolean      NOT NULL DEFAULT false,
    created_at   timestamptz  NOT NULL DEFAULT now(),
    updated_at   timestamptz  NOT NULL DEFAULT now(),

    CONSTRAINT uq_profile_name_per_user UNIQUE (user_id, profile_name)
);

-- Exactly one default profile per user, enforced declaratively rather than
-- by application code. A partial unique index is cheaper and safer than a trigger.
CREATE UNIQUE INDEX uq_one_default_profile_per_user
    ON app.profiles (user_id)
    WHERE is_default;

CREATE TABLE app.profile_allergens (
    profile_id        uuid               NOT NULL REFERENCES app.profiles(profile_id) ON DELETE CASCADE,
    allergen_group_id uuid               NOT NULL REFERENCES kb.allergen_groups(allergen_group_id) ON DELETE RESTRICT,
    severity          app.severity_level NOT NULL DEFAULT 'moderate',
    created_at        timestamptz        NOT NULL DEFAULT now(),
    PRIMARY KEY (profile_id, allergen_group_id)
);

CREATE TABLE app.profile_additives (
    profile_id    uuid        NOT NULL REFERENCES app.profiles(profile_id) ON DELETE CASCADE,
    ingredient_id uuid        NOT NULL REFERENCES kb.ingredients(ingredient_id) ON DELETE CASCADE,
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (profile_id, ingredient_id)
);


-- 6.3  Products -------------------------------------------------------------
CREATE TABLE app.brands (
    brand_id uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    name     citext       NOT NULL UNIQUE,
    country_code char(2)
);

COMMENT ON TABLE app.brands
    IS 'Extracted from app.products: brand name repeated on every product row would be a partial/transitive dependency.';

CREATE TABLE app.products (
    product_id   uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    product_name varchar(250) NOT NULL,
    brand_id     uuid         REFERENCES app.brands(brand_id) ON DELETE SET NULL,
    barcode      varchar(50)  UNIQUE,
    country_code char(2)      NOT NULL DEFAULT 'LK',
    created_at   timestamptz  NOT NULL DEFAULT now(),
    updated_at   timestamptz  NOT NULL DEFAULT now()
);

-- Manufacturers reformulate; the same product can have several label versions
-- over time. Storing the ingredient text on app.products would lose that history.
CREATE TABLE app.product_label_versions (
    label_version_id uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id       uuid        NOT NULL REFERENCES app.products(product_id) ON DELETE CASCADE,
    raw_text         text        NOT NULL,
    text_hash        bytea       GENERATED ALWAYS AS (digest(raw_text, 'sha256')) STORED,
    language_code    varchar(5)  NOT NULL DEFAULT 'en' REFERENCES kb.languages(language_code),
    first_seen_at    timestamptz NOT NULL DEFAULT now(),
    confirmation_count integer   NOT NULL DEFAULT 1
);

CREATE UNIQUE INDEX uq_label_version_hash
    ON app.product_label_versions (product_id, text_hash);


-- 6.4  Scans ----------------------------------------------------------------
CREATE TABLE app.scans (
    scan_id         uuid            PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid            REFERENCES app.users(user_id) ON DELETE CASCADE,     -- NULL = guest scan
    profile_id      uuid            REFERENCES app.profiles(profile_id) ON DELETE SET NULL,
    product_id      uuid            REFERENCES app.products(product_id) ON DELETE SET NULL,
    image_url       varchar(500),                                                        -- NULL unless user consented to retention
    raw_ocr_text    text            NOT NULL,
    ocr_confidence  numeric(5,2)    NOT NULL,
    ocr_engine      app.ocr_engine  NOT NULL DEFAULT 'mlkit_ondevice',
    device_platform app.platform,
    processing_ms   integer,
    status          app.scan_status NOT NULL DEFAULT 'completed',
    scanned_at      timestamptz     NOT NULL DEFAULT now(),

    CONSTRAINT ck_scan_confidence CHECK (ocr_confidence BETWEEN 0 AND 100),
    -- A guest scan cannot carry a profile: enforce the rule in the schema.
    CONSTRAINT ck_scan_profile_requires_user CHECK (profile_id IS NULL OR user_id IS NOT NULL)
);


-- 6.5  Parsed ingredients per scan ------------------------------------------
--  Self-referencing to model nested declarations:
--  "chocolate (sugar, cocoa mass, emulsifier (soy lecithin))"
CREATE TABLE app.scan_ingredients (
    scan_ingredient_id uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_id            uuid         NOT NULL REFERENCES app.scans(scan_id) ON DELETE CASCADE,
    parent_id          uuid         REFERENCES app.scan_ingredients(scan_ingredient_id) ON DELETE CASCADE,
    position_index     smallint     NOT NULL,
    nesting_depth      smallint     NOT NULL DEFAULT 0,
    detected_text      varchar(300) NOT NULL,
    normalised_text    text         GENERATED ALWAYS AS (kb.normalise_text(detected_text)) STORED,
    is_precautionary   boolean      NOT NULL DEFAULT false,  -- from a "may contain traces of" statement

    CONSTRAINT uq_scan_ingredient_position UNIQUE (scan_id, position_index),
    CONSTRAINT ck_nesting_depth CHECK (nesting_depth BETWEEN 0 AND 5)
);

COMMENT ON COLUMN app.scan_ingredients.is_precautionary
    IS 'Precautionary allergen labelling ("may contain traces of") is legally distinct from a declared ingredient and must be presented differently.';


-- 6.6  Match results --------------------------------------------------------
--  Separated from app.scan_ingredients because one detected string may resolve
--  to zero, one, or several knowledge base entries. Collapsing them into one
--  table would force NULLs for unmatched text and lose multi-match results.
CREATE TABLE app.scan_matches (
    match_id           uuid             PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_ingredient_id uuid             NOT NULL REFERENCES app.scan_ingredients(scan_ingredient_id) ON DELETE CASCADE,
    ingredient_id      uuid             NOT NULL REFERENCES kb.ingredients(ingredient_id) ON DELETE CASCADE,
    match_method       app.match_method NOT NULL,
    match_score        real             NOT NULL,
    is_profile_match   boolean          NOT NULL DEFAULT false,   -- set by trigger, never by the client
    created_at         timestamptz      NOT NULL DEFAULT now(),

    CONSTRAINT uq_scan_match UNIQUE (scan_ingredient_id, ingredient_id),
    CONSTRAINT ck_match_score CHECK (match_score BETWEEN 0 AND 1)
);


-- 6.7  Favourites -----------------------------------------------------------
CREATE TABLE app.favourites (
    user_id    uuid        NOT NULL REFERENCES app.users(user_id) ON DELETE CASCADE,
    product_id uuid        NOT NULL REFERENCES app.products(product_id) ON DELETE CASCADE,
    note       varchar(300),
    saved_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, product_id)
);


-- =============================================================================
--  SECTION 7 — AUDIT TABLE (schema: audit)
-- =============================================================================

CREATE TABLE audit.kb_change_log (
    log_id       bigserial   PRIMARY KEY,
    table_name   text        NOT NULL,
    record_id    text        NOT NULL,
    operation    char(1)     NOT NULL,          -- I / U / D
    old_data     jsonb,
    new_data     jsonb,
    changed_by   text        NOT NULL DEFAULT current_user,
    changed_at   timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ck_audit_operation CHECK (operation IN ('I', 'U', 'D'))
);


-- =============================================================================
--  SECTION 8 — INDEXES
--
--  NOTE: PostgreSQL creates an index for PRIMARY KEY and UNIQUE constraints,
--  but NOT for foreign keys. Unindexed FKs cause sequential scans on every
--  cascading delete and on every join. Every FK below is indexed explicitly.
-- =============================================================================

-- 8.1  Foreign key support indexes -----------------------------------------
CREATE INDEX ix_additive_details_category   ON kb.additive_details (additive_category_id);
CREATE INDEX ix_ing_allergens_group         ON kb.ingredient_allergens (allergen_group_id);
CREATE INDEX ix_aliases_ingredient          ON kb.ingredient_aliases (ingredient_id);
CREATE INDEX ix_translations_language       ON kb.ingredient_translations (language_code);
CREATE INDEX ix_user_roles_role             ON app.user_roles (role_id);
CREATE INDEX ix_profiles_user               ON app.profiles (user_id);
CREATE INDEX ix_profile_allergens_group     ON app.profile_allergens (allergen_group_id);
CREATE INDEX ix_profile_additives_ingredient ON app.profile_additives (ingredient_id);
CREATE INDEX ix_products_brand              ON app.products (brand_id);
CREATE INDEX ix_label_versions_product      ON app.product_label_versions (product_id);
CREATE INDEX ix_scans_profile               ON app.scans (profile_id);
CREATE INDEX ix_scans_product               ON app.scans (product_id);
CREATE INDEX ix_scan_ingredients_scan       ON app.scan_ingredients (scan_id);
CREATE INDEX ix_scan_ingredients_parent     ON app.scan_ingredients (parent_id) WHERE parent_id IS NOT NULL;
CREATE INDEX ix_scan_matches_scan_ingredient ON app.scan_matches (scan_ingredient_id);
CREATE INDEX ix_scan_matches_ingredient     ON app.scan_matches (ingredient_id);
CREATE INDEX ix_favourites_product          ON app.favourites (product_id);


-- 8.2  Trigram indexes for fuzzy OCR matching -------------------------------
--  GIN + gin_trgm_ops supports the % similarity operator. This is what makes
--  "emulsifer" match "emulsifier" without a full table scan.
CREATE INDEX ix_ingredients_name_trgm
    ON kb.ingredients USING gin (normalised_name gin_trgm_ops);

CREATE INDEX ix_aliases_trgm
    ON kb.ingredient_aliases USING gin (normalised_alias gin_trgm_ops);


-- 8.3  Vector index for semantic matching -----------------------------------
--  HNSW is chosen over IVFFlat because it needs no training pass, tolerates
--  incremental inserts as the knowledge base grows, and gives better recall
--  at this dataset size (~10k rows). Recall matters more than raw speed here:
--  a missed semantic match is a missed allergen.
--
--  m               = 16  neighbours per node (build time vs recall)
--  ef_construction = 64  candidate list size during build
CREATE INDEX ix_embeddings_hnsw
    ON kb.ingredient_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Query-time recall knob. Set per session in the application:
--   SET LOCAL hnsw.ef_search = 60;


-- 8.4  Query-pattern indexes ------------------------------------------------

-- Scan history screen: newest first, paginated, per user.
CREATE INDEX ix_scans_user_recent
    ON app.scans (user_id, scanned_at DESC)
    WHERE user_id IS NOT NULL;

-- Covering index: serves the history list without touching the heap.
CREATE INDEX ix_scans_history_covering
    ON app.scans (user_id, scanned_at DESC)
    INCLUDE (product_id, ocr_confidence, status)
    WHERE user_id IS NOT NULL AND status = 'completed';

-- Admin review queue: pending unrecognised terms, most frequent first.
CREATE INDEX ix_unrecognised_pending
    ON kb.unrecognised_terms (occurrence_count DESC, last_seen_at DESC)
    WHERE status = 'pending';

-- Only additives carry an E-number; a partial index keeps it small.
CREATE INDEX ix_additive_e_number
    ON kb.additive_details (e_number)
    WHERE e_number IS NOT NULL;

-- Safety-critical read path: pull every profile-matching hit for a scan.
CREATE INDEX ix_scan_matches_profile_hits
    ON app.scan_matches (scan_ingredient_id)
    WHERE is_profile_match;

-- Active knowledge base entries by type, for admin filtering.
CREATE INDEX ix_ingredients_type_active
    ON kb.ingredients (ingredient_type)
    WHERE is_active;

-- Append-only, time-ordered: BRIN is a fraction of the size of a B-tree here.
CREATE INDEX ix_audit_changed_at_brin
    ON audit.kb_change_log USING brin (changed_at);

-- Stale embeddings awaiting regeneration by the background job.
CREATE INDEX ix_embeddings_stale
    ON kb.ingredient_embeddings (ingredient_id)
    WHERE is_stale;


-- =============================================================================
--  SECTION 9 — FUNCTIONS
-- =============================================================================

-- 9.1  The three-stage matching cascade -------------------------------------
--  Stage 1  exact canonical name        score 1.00
--  Stage 2  curated alias               score 0.98
--  Stage 3  trigram fuzzy (OCR errors)  score = similarity()
--  Stage 4  vector cosine similarity    score = 1 - cosine distance
--
--  Each stage runs only if the previous stage found nothing, so the expensive
--  vector search is reached only for genuinely unfamiliar text.
CREATE OR REPLACE FUNCTION kb.fn_match_ingredient(
    p_raw_text          text,
    p_embedding         vector(384) DEFAULT NULL,
    p_fuzzy_threshold   real        DEFAULT 0.45,
    p_vector_threshold  real        DEFAULT 0.55,
    p_max_results       integer     DEFAULT 5
)
RETURNS TABLE (
    ingredient_id   uuid,
    canonical_name  text,
    match_method    app.match_method,
    match_score     real
)
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_norm text := kb.normalise_text(p_raw_text);
BEGIN
    IF v_norm IS NULL THEN
        RETURN;
    END IF;

    -- Stage 1 — exact canonical name
    RETURN QUERY
        SELECT i.ingredient_id,
               i.canonical_name::text,
               'exact'::app.match_method,
               1.0::real
        FROM kb.ingredients i
        WHERE i.normalised_name = v_norm
          AND i.is_active
        LIMIT p_max_results;
    IF FOUND THEN RETURN; END IF;

    -- Stage 2 — curated alias
    RETURN QUERY
        SELECT i.ingredient_id,
               i.canonical_name::text,
               'alias'::app.match_method,
               0.98::real
        FROM kb.ingredient_aliases a
        JOIN kb.ingredients i ON i.ingredient_id = a.ingredient_id
        WHERE a.normalised_alias = v_norm
          AND a.is_active
          AND i.is_active
        LIMIT p_max_results;
    IF FOUND THEN RETURN; END IF;

    -- Stage 3 — trigram fuzzy match, tolerating OCR character errors
    RETURN QUERY
        SELECT m.ingredient_id, m.canonical_name, m.match_method, m.match_score
        FROM (
            SELECT DISTINCT ON (i.ingredient_id)
                   i.ingredient_id,
                   i.canonical_name::text  AS canonical_name,
                   'fuzzy'::app.match_method AS match_method,
                   similarity(a.normalised_alias, v_norm)::real AS match_score
            FROM kb.ingredient_aliases a
            JOIN kb.ingredients i ON i.ingredient_id = a.ingredient_id
            WHERE a.normalised_alias % v_norm
              AND similarity(a.normalised_alias, v_norm) >= p_fuzzy_threshold
              AND a.is_active
              AND i.is_active
            ORDER BY i.ingredient_id, similarity(a.normalised_alias, v_norm) DESC
        ) m
        ORDER BY m.match_score DESC
        LIMIT p_max_results;
    IF FOUND THEN RETURN; END IF;

    -- Stage 4 — semantic similarity over embeddings
    IF p_embedding IS NOT NULL THEN
        RETURN QUERY
            SELECT i.ingredient_id,
                   i.canonical_name::text,
                   'semantic'::app.match_method,
                   (1 - (e.embedding <=> p_embedding))::real
            FROM kb.ingredient_embeddings e
            JOIN kb.ingredients i ON i.ingredient_id = e.ingredient_id
            WHERE i.is_active
              AND NOT e.is_stale
              AND (1 - (e.embedding <=> p_embedding)) >= p_vector_threshold
            ORDER BY e.embedding <=> p_embedding
            LIMIT p_max_results;
    END IF;

    RETURN;
END;
$$;


-- 9.2  Record an unrecognised term (knowledge base growth loop) -------------
CREATE OR REPLACE FUNCTION kb.fn_log_unrecognised_term(p_raw_text text)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_norm text := kb.normalise_text(p_raw_text);
BEGIN
    IF v_norm IS NULL OR length(v_norm) < 3 THEN
        RETURN;
    END IF;

    INSERT INTO kb.unrecognised_terms (normalised_term, sample_raw_text)
    VALUES (v_norm, p_raw_text)
    ON CONFLICT (normalised_term) DO UPDATE
        SET occurrence_count = kb.unrecognised_terms.occurrence_count + 1,
            last_seen_at     = now();
END;
$$;


-- 9.3  Aggregated scan result for the mobile client -------------------------
--  Returns the full result payload in one round trip, ordered by the
--  three-tier hierarchy specified in the proposal: personal allergens first,
--  then other allergens, then additives.
CREATE OR REPLACE FUNCTION app.fn_scan_summary(
    p_scan_id  uuid,
    p_language varchar(5) DEFAULT 'en'
)
RETURNS jsonb
LANGUAGE sql
STABLE
AS $$
    SELECT jsonb_build_object(
        'scan_id',        s.scan_id,
        'scanned_at',     s.scanned_at,
        'ocr_confidence', s.ocr_confidence,
        'ocr_engine',     s.ocr_engine,
        'total_parsed',   (SELECT count(*) FROM app.scan_ingredients si WHERE si.scan_id = s.scan_id),
        'unmatched',      (
            SELECT count(*)
            FROM app.scan_ingredients si
            WHERE si.scan_id = s.scan_id
              AND NOT EXISTS (SELECT 1 FROM app.scan_matches sm WHERE sm.scan_ingredient_id = si.scan_ingredient_id)
        ),
        'findings', COALESCE((
            SELECT jsonb_agg(f ORDER BY f.tier, f.match_score DESC)
            FROM (
                SELECT
                    CASE
                        WHEN sm.is_profile_match             THEN 1   -- tier 1: your allergens
                        WHEN i.ingredient_type = 'allergen_source' THEN 2 -- tier 2: other allergens
                        ELSE 3                                       -- tier 3: additives
                    END                                   AS tier,
                    si.detected_text,
                    si.is_precautionary,
                    i.canonical_name::text                AS canonical_name,
                    i.ingredient_type,
                    sm.match_method,
                    sm.match_score,
                    sm.is_profile_match,
                    ad.e_number,
                    ac.name                               AS additive_category,
                    tr.display_name                       AS localised_name,
                    tr.explanation                        AS localised_explanation
                FROM app.scan_ingredients si
                JOIN app.scan_matches   sm ON sm.scan_ingredient_id = si.scan_ingredient_id
                JOIN kb.ingredients      i ON i.ingredient_id = sm.ingredient_id
                LEFT JOIN kb.additive_details    ad ON ad.ingredient_id = i.ingredient_id
                LEFT JOIN kb.additive_categories ac ON ac.additive_category_id = ad.additive_category_id
                LEFT JOIN kb.ingredient_translations tr
                       ON tr.ingredient_id = i.ingredient_id AND tr.language_code = p_language
                WHERE si.scan_id = s.scan_id
            ) f
        ), '[]'::jsonb)
    )
    FROM app.scans s
    WHERE s.scan_id = p_scan_id;
$$;


-- =============================================================================
--  SECTION 10 — TRIGGER FUNCTIONS AND TRIGGERS
-- =============================================================================

-- 10.1  updated_at maintenance ---------------------------------------------
CREATE TRIGGER trg_allergen_groups_updated   BEFORE UPDATE ON kb.allergen_groups
    FOR EACH ROW EXECUTE FUNCTION app.fn_set_updated_at();
CREATE TRIGGER trg_ingredients_updated       BEFORE UPDATE ON kb.ingredients
    FOR EACH ROW EXECUTE FUNCTION app.fn_set_updated_at();
CREATE TRIGGER trg_ing_translations_updated  BEFORE UPDATE ON kb.ingredient_translations
    FOR EACH ROW EXECUTE FUNCTION app.fn_set_updated_at();
CREATE TRIGGER trg_users_updated             BEFORE UPDATE ON app.users
    FOR EACH ROW EXECUTE FUNCTION app.fn_set_updated_at();
CREATE TRIGGER trg_profiles_updated          BEFORE UPDATE ON app.profiles
    FOR EACH ROW EXECUTE FUNCTION app.fn_set_updated_at();
CREATE TRIGGER trg_products_updated          BEFORE UPDATE ON app.products
    FOR EACH ROW EXECUTE FUNCTION app.fn_set_updated_at();


-- 10.2  Profile match flag (SAFETY CRITICAL) -------------------------------
--  This is the strongest argument for a trigger in the whole schema. The flag
--  that decides whether a red allergen warning is shown must not depend on
--  the API layer remembering to compute it. Any writer — the API, a batch
--  reprocessing job, a manual SQL fix — gets the correct value.
CREATE OR REPLACE FUNCTION app.fn_flag_profile_match()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_profile_id uuid;
    v_hit        boolean;
BEGIN
    SELECT s.profile_id
      INTO v_profile_id
      FROM app.scan_ingredients si
      JOIN app.scans s ON s.scan_id = si.scan_id
     WHERE si.scan_ingredient_id = NEW.scan_ingredient_id;

    IF v_profile_id IS NULL THEN
        NEW.is_profile_match := false;   -- guest scan: no personalisation
        RETURN NEW;
    END IF;

    SELECT EXISTS (
        -- allergen group hit
        SELECT 1
        FROM kb.ingredient_allergens ia
        JOIN app.profile_allergens   pa ON pa.allergen_group_id = ia.allergen_group_id
        WHERE ia.ingredient_id = NEW.ingredient_id
          AND pa.profile_id    = v_profile_id
        UNION ALL
        -- explicitly avoided additive
        SELECT 1
        FROM app.profile_additives pad
        WHERE pad.profile_id    = v_profile_id
          AND pad.ingredient_id = NEW.ingredient_id
    ) INTO v_hit;

    NEW.is_profile_match := v_hit;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_scan_match_profile_flag
    BEFORE INSERT OR UPDATE OF ingredient_id ON app.scan_matches
    FOR EACH ROW EXECUTE FUNCTION app.fn_flag_profile_match();


-- 10.3  Invalidate embeddings when the source text changes ------------------
--  An embedding generated from an old canonical name is silently wrong. This
--  marks it stale so the regeneration job picks it up, instead of leaving a
--  mismatched vector in the index indefinitely.
CREATE OR REPLACE FUNCTION kb.fn_invalidate_embedding()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.canonical_name IS DISTINCT FROM OLD.canonical_name THEN
        UPDATE kb.ingredient_embeddings
           SET is_stale = true
         WHERE ingredient_id = NEW.ingredient_id;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_ingredient_embedding_stale
    AFTER UPDATE OF canonical_name ON kb.ingredients
    FOR EACH ROW EXECUTE FUNCTION kb.fn_invalidate_embedding();


-- 10.4  Auto-demote the previous default profile ---------------------------
--  The partial unique index rejects a second default; this trigger makes
--  "set this one as default" work without the client having to clear the old
--  one first.
CREATE OR REPLACE FUNCTION app.fn_demote_previous_default()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.is_default THEN
        UPDATE app.profiles
           SET is_default = false
         WHERE user_id    = NEW.user_id
           AND profile_id <> NEW.profile_id
           AND is_default;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_profile_single_default
    BEFORE INSERT OR UPDATE OF is_default ON app.profiles
    FOR EACH ROW WHEN (NEW.is_default) EXECUTE FUNCTION app.fn_demote_previous_default();


-- 10.5  Knowledge base audit trail ------------------------------------------
CREATE OR REPLACE FUNCTION audit.fn_log_kb_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_op char(1);
    v_id text;
BEGIN
    v_op := CASE TG_OP WHEN 'INSERT' THEN 'I' WHEN 'UPDATE' THEN 'U' ELSE 'D' END;
    v_id := CASE TG_OP WHEN 'DELETE' THEN OLD.ingredient_id::text ELSE NEW.ingredient_id::text END;

    INSERT INTO audit.kb_change_log (table_name, record_id, operation, old_data, new_data)
    VALUES (
        TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME,
        v_id,
        v_op,
        CASE WHEN TG_OP IN ('UPDATE','DELETE') THEN to_jsonb(OLD) END,
        CASE WHEN TG_OP IN ('INSERT','UPDATE') THEN to_jsonb(NEW) END
    );

    RETURN CASE TG_OP WHEN 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE TRIGGER trg_audit_ingredients
    AFTER INSERT OR UPDATE OR DELETE ON kb.ingredients
    FOR EACH ROW EXECUTE FUNCTION audit.fn_log_kb_change();

CREATE TRIGGER trg_audit_ingredient_allergens
    AFTER INSERT OR UPDATE OR DELETE ON kb.ingredient_allergens
    FOR EACH ROW EXECUTE FUNCTION audit.fn_log_kb_change();


-- 10.6  Confirm repeat label sightings --------------------------------------
CREATE OR REPLACE FUNCTION app.fn_bump_label_confirmation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE app.product_label_versions
       SET confirmation_count = confirmation_count + 1
     WHERE product_id = NEW.product_id
       AND text_hash  = digest(NEW.raw_ocr_text, 'sha256');
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_scan_confirms_label
    AFTER INSERT ON app.scans
    FOR EACH ROW WHEN (NEW.product_id IS NOT NULL)
    EXECUTE FUNCTION app.fn_bump_label_confirmation();


-- =============================================================================
--  SECTION 11 — MATERIALISED VIEW (fast offline sync payload)
--
--  The mobile client caches a flattened allergen lookup for offline scanning.
--  Computing this join on every sync is wasteful; the data changes rarely.
-- =============================================================================

CREATE MATERIALIZED VIEW kb.mv_allergen_lookup AS
SELECT
    i.ingredient_id,
    i.normalised_name,
    i.ingredient_type,
    ag.code                AS allergen_code,
    ia.certainty,
    ad.e_number,
    ac.code                AS additive_category_code
FROM kb.ingredients i
LEFT JOIN kb.ingredient_allergens ia ON ia.ingredient_id = i.ingredient_id
LEFT JOIN kb.allergen_groups      ag ON ag.allergen_group_id = ia.allergen_group_id
LEFT JOIN kb.additive_details     ad ON ad.ingredient_id = i.ingredient_id
LEFT JOIN kb.additive_categories  ac ON ac.additive_category_id = ad.additive_category_id
WHERE i.is_active;

-- REFRESH CONCURRENTLY requires a unique index on the view.
CREATE UNIQUE INDEX uq_mv_allergen_lookup
    ON kb.mv_allergen_lookup (ingredient_id, COALESCE(allergen_code, ''));

CREATE INDEX ix_mv_allergen_lookup_name
    ON kb.mv_allergen_lookup USING gin (normalised_name gin_trgm_ops);

-- Refresh without blocking readers:
--   REFRESH MATERIALIZED VIEW CONCURRENTLY kb.mv_allergen_lookup;


-- =============================================================================
--  SECTION 12 — SCHEDULED MAINTENANCE (pg_cron)
--
--  NEON LIMITATION: cron.schedule_in_database() is not available, so pg_cron
--  jobs run only against the 'postgres' database. If the application database
--  is named anything else, schedule these from GitHub Actions instead by
--  calling a protected /internal/maintenance endpoint on the FastAPI service.
-- =============================================================================

-- SELECT cron.schedule('refresh-allergen-lookup', '0 3 * * *',
--     $$REFRESH MATERIALIZED VIEW CONCURRENTLY kb.mv_allergen_lookup$$);
--
-- SELECT cron.schedule('purge-old-guest-scans', '30 3 * * *',
--     $$DELETE FROM app.scans WHERE user_id IS NULL AND scanned_at < now() - interval '30 days'$$);
--
-- SELECT cron.schedule('vacuum-scan-matches', '0 4 * * 0',
--     $$VACUUM ANALYZE app.scan_matches$$);


-- =============================================================================
--  SECTION 13 — SEED DATA DEMONSTRATING THE HIDDEN-ALLERGEN CASE
-- =============================================================================

WITH new_ing AS (
    INSERT INTO kb.ingredients (canonical_name, ingredient_type) VALUES
        ('Soy lecithin',         'additive'),
        ('Whey powder',          'allergen_source'),
        ('Casein',               'allergen_source'),
        ('Monosodium glutamate', 'additive'),
        ('Tartrazine',           'additive')
    RETURNING ingredient_id, canonical_name
)
INSERT INTO kb.ingredient_allergens (ingredient_id, allergen_group_id, certainty)
SELECT n.ingredient_id, ag.allergen_group_id, 'definite'
FROM new_ing n
JOIN kb.allergen_groups ag
  ON (n.canonical_name = 'Soy lecithin' AND ag.code = 'SOY')
  OR (n.canonical_name IN ('Whey powder','Casein') AND ag.code = 'MILK');

INSERT INTO kb.additive_details (ingredient_id, e_number, additive_category_id, concern_level)
SELECT i.ingredient_id, v.e_num, ac.additive_category_id, v.concern
FROM (VALUES
        ('Soy lecithin',         'E322', 'EMULSIFIER',       1),
        ('Monosodium glutamate', 'E621', 'FLAVOUR_ENHANCER', 2),
        ('Tartrazine',           'E102', 'COLOUR',           3)
     ) AS v(name, e_num, cat_code, concern)
JOIN kb.ingredients i         ON i.canonical_name = v.name
JOIN kb.additive_categories ac ON ac.code = v.cat_code;

-- Aliases: how these actually appear on Sri Lankan packaging.
INSERT INTO kb.ingredient_aliases (ingredient_id, alias_text)
SELECT i.ingredient_id, v.alias
FROM (VALUES
        ('Soy lecithin',         'lecithin'),
        ('Soy lecithin',         'soya lecithin'),
        ('Soy lecithin',         'E322'),
        ('Soy lecithin',         'emulsifier (soya lecithin)'),
        ('Whey powder',          'whey'),
        ('Whey powder',          'whey solids'),
        ('Casein',               'sodium caseinate'),
        ('Casein',               'milk protein'),
        ('Monosodium glutamate', 'E621'),
        ('Monosodium glutamate', 'MSG'),
        ('Monosodium glutamate', 'flavour enhancer (E621)'),
        ('Tartrazine',           'E102')
     ) AS v(name, alias)
JOIN kb.ingredients i ON i.canonical_name = v.name;

ANALYZE;


-- =============================================================================
--  NORMALISATION NOTES  (for the report / viva defence)
--
--  1NF  Every column holds a single atomic value. No comma-separated allergen
--       lists, no arrays used as a substitute for a junction table. The parsed
--       ingredient list is decomposed into app.scan_ingredients rows.
--
--  2NF  No partial dependency on part of a composite key. In
--       kb.ingredient_translations the PK is (ingredient_id, language_code)
--       and every non-key column — display_name, explanation — depends on the
--       whole key, not on either half alone.
--
--  3NF  No transitive dependencies:
--       * additive category name/description moved to kb.additive_categories
--         (they depend on the category, not on the additive);
--       * brand name moved to app.brands (depends on the brand, not the product);
--       * language name moved to kb.languages (app.users stores only the FK);
--       * embeddings moved to kb.ingredient_embeddings (depend on the pair
--         (ingredient, model), not on the ingredient alone);
--       * translations moved out of kb.ingredients (depend on the pair
--         (ingredient, language) — inline _si/_ta columns would be a
--         repeating group requiring a migration per new language).
--
--  Deliberate denormalisation, and why it is safe:
--       * normalised_name / normalised_alias / text_hash are STORED GENERATED
--         columns. They are derived, but the database computes them, so they
--         cannot drift from their source — the risk normalisation guards
--         against does not apply.
--       * kb.mv_allergen_lookup is a materialised view, explicitly refreshed.
--         It is a cache, not a second source of truth.
-- =============================================================================