"""Reflects the `kb` schema (sql/00_schema.sql SECTION 5). Reference data:
ingredients, allergens, additives, aliases, translations, unrecognised terms."""

from sqlalchemy import Boolean, Column, ForeignKey, Integer, MetaData, SmallInteger, String, Table, Text, text
from sqlalchemy.dialects.postgresql import CITEXT, TIMESTAMP, UUID
from sqlalchemy.dialects.postgresql import ENUM as PGEnum

metadata = MetaData(schema="kb")

# create_type=False on all three: the Postgres ENUM types already exist
# (created by sql/00_schema.sql SECTION 3) — these objects exist only to
# tell SQLAlchemy/asyncpg what type OID to bind values as on INSERT/UPDATE.
# Without this, asyncpg sends plain VARCHAR and Postgres raises
# "column ... is of type kb.x but expression is of type character varying"
# (confirmed live against Neon — this bit every writable enum column here,
# including ones only ever written through the SQLAdmin panel).
ingredient_type_enum = PGEnum("allergen_source", "additive", "neutral", name="ingredient_type", schema="kb", create_type=False)
allergen_certainty_enum = PGEnum("definite", "probable", "possible", name="allergen_certainty", schema="kb", create_type=False)
term_status_enum = PGEnum("pending", "mapped", "ignored", name="term_status", schema="kb", create_type=False)

allergen_groups = Table(
    "allergen_groups",
    metadata,
    Column("allergen_group_id", UUID(as_uuid=True), primary_key=True),
    Column("code", String(30), nullable=False, unique=True),
    Column("is_major", Boolean, nullable=False),
    Column("icon_code", String(50), nullable=False),
    Column("display_order", SmallInteger, nullable=False),
    Column("is_active", Boolean, nullable=False),
)

allergen_group_translations = Table(
    "allergen_group_translations",
    metadata,
    Column("allergen_group_id", UUID(as_uuid=True), ForeignKey("kb.allergen_groups.allergen_group_id"), primary_key=True),
    Column("language_code", String(5), primary_key=True),
    Column("display_name", String(100), nullable=False),
    Column("description", Text),
)

additive_categories = Table(
    "additive_categories",
    metadata,
    Column("additive_category_id", SmallInteger, primary_key=True),
    Column("code", String(40), nullable=False, unique=True),
    Column("name", String(80), nullable=False),
    Column("description", Text),
)

ingredients = Table(
    "ingredients",
    metadata,
    Column("ingredient_id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("canonical_name", CITEXT, nullable=False, unique=True),
    Column("normalised_name", Text),  # generated column, read-only
    Column("ingredient_type", ingredient_type_enum, nullable=False),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    Column("created_at", TIMESTAMP(timezone=True)),
    Column("updated_at", TIMESTAMP(timezone=True)),
)

additive_details = Table(
    "additive_details",
    metadata,
    Column("ingredient_id", UUID(as_uuid=True), ForeignKey("kb.ingredients.ingredient_id"), primary_key=True),
    Column("e_number", String(15), unique=True),
    Column("additive_category_id", SmallInteger, ForeignKey("kb.additive_categories.additive_category_id"), nullable=False),
    Column("concern_level", SmallInteger, nullable=False),
    Column("adi_mg_per_kg_bw", String),  # numeric, read as string to avoid float precision surprises
    Column("is_permitted_lk", Boolean, nullable=False),
)

ingredient_allergens = Table(
    "ingredient_allergens",
    metadata,
    Column("ingredient_id", UUID(as_uuid=True), ForeignKey("kb.ingredients.ingredient_id"), primary_key=True),
    Column("allergen_group_id", UUID(as_uuid=True), ForeignKey("kb.allergen_groups.allergen_group_id"), primary_key=True),
    Column("certainty", allergen_certainty_enum, nullable=False),
    Column("note", Text),
)

ingredient_aliases = Table(
    "ingredient_aliases",
    metadata,
    Column("alias_id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("ingredient_id", UUID(as_uuid=True), ForeignKey("kb.ingredients.ingredient_id"), nullable=False),
    Column("alias_text", CITEXT, nullable=False),
    Column("normalised_alias", Text),  # generated column, read-only
    Column("language_code", String(5), nullable=False),
    Column("is_curated", Boolean, nullable=False),
    Column("is_active", Boolean, nullable=False),
)

ingredient_translations = Table(
    "ingredient_translations",
    metadata,
    Column("ingredient_id", UUID(as_uuid=True), ForeignKey("kb.ingredients.ingredient_id"), primary_key=True),
    Column("language_code", String(5), primary_key=True),
    Column("display_name", String(200), nullable=False),
    Column("explanation", Text),
    Column("generated_by", String(20), nullable=False),
    Column("model_version", String(40)),
)

unrecognised_terms = Table(
    "unrecognised_terms",
    metadata,
    Column("term_id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("normalised_term", Text, nullable=False, unique=True),
    Column("sample_raw_text", Text, nullable=False),
    Column("occurrence_count", Integer, nullable=False),
    Column("status", term_status_enum, nullable=False),
    Column("resolved_ingredient_id", UUID(as_uuid=True), ForeignKey("kb.ingredients.ingredient_id")),
    Column("first_seen_at", TIMESTAMP(timezone=True)),
    Column("last_seen_at", TIMESTAMP(timezone=True)),
)

mv_allergen_lookup = Table(
    "mv_allergen_lookup",
    metadata,
    Column("ingredient_id", UUID(as_uuid=True)),
    Column("normalised_name", Text),
    Column("ingredient_type", String),
    Column("allergen_code", String),
    Column("certainty", String),
    Column("e_number", String(15)),
    Column("additive_category_code", String),
)
