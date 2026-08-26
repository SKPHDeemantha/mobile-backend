from sqlalchemy import BigInteger, Column, MetaData, String, Table, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

metadata = MetaData(schema="audit")

kb_change_log = Table(
    "kb_change_log",
    metadata,
    Column("log_id", BigInteger, primary_key=True),
    Column("table_name", Text, nullable=False),
    Column("record_id", Text, nullable=False),
    Column("operation", String(1), nullable=False),
    Column("old_data", JSONB),
    Column("new_data", JSONB),
    Column("changed_by", Text, nullable=False),
    Column("changed_at", TIMESTAMP(timezone=True)),
)
