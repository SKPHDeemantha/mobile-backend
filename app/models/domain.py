"""Reflects the `app` schema (sql/00_schema.sql SECTION 6 + migration 0001).
Transactional data: users, profiles, products, scans, favourites."""

from sqlalchemy import Boolean, Column, ForeignKey, Integer, MetaData, Numeric, SmallInteger, String, Table, Text, text
from sqlalchemy.dialects.postgresql import CITEXT, TIMESTAMP, UUID

metadata = MetaData(schema="app")

roles = Table(
    "roles",
    metadata,
    Column("role_id", SmallInteger, primary_key=True),
    Column("code", String(30), nullable=False, unique=True),
    Column("name", String(60), nullable=False),
)

users = Table(
    "users",
    metadata,
    Column("user_id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("email", CITEXT, nullable=False, unique=True),
    Column("password_hash", String(255), nullable=False),
    Column("display_name", String(150), nullable=False),
    Column("preferred_language", String(5), nullable=False, server_default="en"),
    Column("email_verified_at", TIMESTAMP(timezone=True)),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    Column("created_at", TIMESTAMP(timezone=True)),
    Column("updated_at", TIMESTAMP(timezone=True)),
)

user_roles = Table(
    "user_roles",
    metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("app.users.user_id"), primary_key=True),
    Column("role_id", SmallInteger, ForeignKey("app.roles.role_id"), primary_key=True),
    Column("granted_at", TIMESTAMP(timezone=True)),
)

# Added by sql/migrations/0001_refresh_tokens.sql — not in 00_schema.sql.
refresh_tokens = Table(
    "refresh_tokens",
    metadata,
    Column("token_id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("app.users.user_id"), nullable=False),
    Column("issued_at", TIMESTAMP(timezone=True)),
    Column("expires_at", TIMESTAMP(timezone=True), nullable=False),
    Column("revoked_at", TIMESTAMP(timezone=True)),
    Column("replaced_by", UUID(as_uuid=True), ForeignKey("app.refresh_tokens.token_id")),
)

profiles = Table(
    "profiles",
    metadata,
    Column("profile_id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("user_id", UUID(as_uuid=True), ForeignKey("app.users.user_id"), nullable=False),
    Column("profile_name", String(100), nullable=False),
    Column("is_default", Boolean, nullable=False, server_default=text("false")),
    Column("created_at", TIMESTAMP(timezone=True)),
    Column("updated_at", TIMESTAMP(timezone=True)),
)

profile_allergens = Table(
    "profile_allergens",
    metadata,
    Column("profile_id", UUID(as_uuid=True), ForeignKey("app.profiles.profile_id"), primary_key=True),
    Column("allergen_group_id", UUID(as_uuid=True), primary_key=True),
    Column("severity", String, nullable=False),  # app.severity_level enum
)

profile_additives = Table(
    "profile_additives",
    metadata,
    Column("profile_id", UUID(as_uuid=True), ForeignKey("app.profiles.profile_id"), primary_key=True),
    Column("ingredient_id", UUID(as_uuid=True), primary_key=True),
)

brands = Table(
    "brands",
    metadata,
    Column("brand_id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("name", CITEXT, nullable=False, unique=True),
    Column("country_code", String(2)),
)

products = Table(
    "products",
    metadata,
    Column("product_id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("product_name", String(250), nullable=False),
    Column("brand_id", UUID(as_uuid=True), ForeignKey("app.brands.brand_id")),
    Column("barcode", String(50), unique=True),
    Column("country_code", String(2), nullable=False, server_default="LK"),
)

product_label_versions = Table(
    "product_label_versions",
    metadata,
    Column("label_version_id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("product_id", UUID(as_uuid=True), ForeignKey("app.products.product_id"), nullable=False),
    Column("raw_text", Text, nullable=False),
    Column("language_code", String(5), nullable=False, server_default="en"),
    Column("first_seen_at", TIMESTAMP(timezone=True)),
    Column("confirmation_count", Integer, nullable=False),
)

scans = Table(
    "scans",
    metadata,
    Column("scan_id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("user_id", UUID(as_uuid=True), ForeignKey("app.users.user_id")),
    Column("profile_id", UUID(as_uuid=True), ForeignKey("app.profiles.profile_id")),
    Column("product_id", UUID(as_uuid=True), ForeignKey("app.products.product_id")),
    Column("image_url", String(500)),
    Column("raw_ocr_text", Text, nullable=False),
    Column("ocr_confidence", Numeric(5, 2), nullable=False),
    Column("ocr_engine", String, nullable=False),  # app.ocr_engine enum
    Column("device_platform", String),  # app.platform enum
    Column("processing_ms", Integer),
    Column("status", String, nullable=False),  # app.scan_status enum
    Column("scanned_at", TIMESTAMP(timezone=True)),
)

scan_ingredients = Table(
    "scan_ingredients",
    metadata,
    Column("scan_ingredient_id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("scan_id", UUID(as_uuid=True), ForeignKey("app.scans.scan_id"), nullable=False),
    Column("parent_id", UUID(as_uuid=True), ForeignKey("app.scan_ingredients.scan_ingredient_id")),
    Column("position_index", SmallInteger, nullable=False),
    Column("nesting_depth", SmallInteger, nullable=False, server_default="0"),
    Column("detected_text", String(300), nullable=False),
    Column("normalised_text", Text),  # generated column, read-only
    Column("is_precautionary", Boolean, nullable=False, server_default=text("false")),
)

scan_matches = Table(
    "scan_matches",
    metadata,
    Column("match_id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("scan_ingredient_id", UUID(as_uuid=True), ForeignKey("app.scan_ingredients.scan_ingredient_id"), nullable=False),
    Column("ingredient_id", UUID(as_uuid=True), nullable=False),
    Column("match_method", String, nullable=False),  # app.match_method enum
    Column("match_score", Numeric, nullable=False),
    Column("is_profile_match", Boolean, nullable=False, server_default=text("false")),  # trigger-computed; never write this from Python
)

favourites = Table(
    "favourites",
    metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("app.users.user_id"), primary_key=True),
    Column("product_id", UUID(as_uuid=True), ForeignKey("app.products.product_id"), primary_key=True),
    Column("note", String(300)),
    Column("saved_at", TIMESTAMP(timezone=True)),
)
