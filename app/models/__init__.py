"""SQLAlchemy Core Table objects describing the schema defined in
sql/00_schema.sql. These are DESCRIPTIVE ONLY — nothing here ever calls
`metadata.create_all()`. The .sql files are the single source of truth for
DDL; these Table objects exist so the rest of the app gets typed, IDE-checked
query building instead of hand-written column-name strings everywhere."""

from app.models.audit import metadata as audit_metadata  # noqa: F401
from app.models.domain import metadata as app_metadata  # noqa: F401
from app.models.kb import metadata as kb_metadata  # noqa: F401
