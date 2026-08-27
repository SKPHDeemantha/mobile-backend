"""Connection-string cleanup shared by app/core/db.py and the standalone
scripts/*.py. Kept dependency-free (stdlib only, no pydantic-settings) so
the scripts can import it without needing every Settings field populated.

Two DIFFERENT sets of Neon-supplied query parameters need handling, and they
need DIFFERENT fixes because they're consumed through two different code
paths:

  channel_binding=require   asyncpg's own DSN-string parser (used by both
                             asyncpg.connect(dsn) directly AND indirectly
                             by SQLAlchemy) has no concept of this parameter
                             at all and raises on it either way. Always
                             stripped. Safe to drop: it's a supplementary
                             SCRAM/TLS anti-MITM hardening layer on top of
                             the TLS connection, not a replacement for it.

  sslmode=require            asyncpg's DSN-STRING parser understands this
                             fine (confirmed live) — so scripts calling
                             asyncpg.connect(dsn_string) directly are okay.
                             But SQLAlchemy's asyncpg dialect does NOT parse
                             the URL itself; it takes each query parameter
                             and forwards it as a bare Python keyword
                             argument to asyncpg.connect(...,
                             sslmode="require"), and asyncpg.connect() has
                             no 'sslmode' parameter (only 'ssl') — confirmed
                             live: "TypeError: connect() got an unexpected
                             keyword argument 'sslmode'". For the
                             SQLAlchemy/create_async_engine path this is
                             stripped from the URL too, and app/core/db.py
                             passes `ssl=True` explicitly via connect_args
                             instead, which IS a valid asyncpg.connect() kwarg.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_STRIP_ALWAYS = {"channel_binding"}
_STRIP_FOR_SQLALCHEMY = _STRIP_ALWAYS | {"sslmode"}


def _strip(url: str, params: set[str]) -> str:
    parts = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in params]
    return urlunsplit(parts._replace(query=urlencode(kept)))


def sanitize_pg_url(url: str) -> str:
    """For SQLAlchemy's create_async_engine(): strips both channel_binding
    and sslmode (SSL is instead requested explicitly via connect_args=
    {"ssl": True} in app/core/db.py — see module docstring for why)."""
    return _strip(url, _STRIP_FOR_SQLALCHEMY)


def wants_ssl(url: str) -> bool:
    """Whether the ORIGINAL url asked for TLS (sslmode=require, the case for
    every Neon connection string). Local docker-compose Postgres URLs (see
    tests/conftest.py, docker-compose.yml) have no sslmode param and don't
    run TLS at all — forcing ssl=True there would break every test."""
    parts = urlsplit(url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    return params.get("sslmode", "").lower() not in ("", "disable")


def to_asyncpg_dsn(url: str) -> str:
    """For scripts calling asyncpg.connect(dsn_string) directly: plain
    'postgresql://' scheme, only channel_binding stripped — sslmode is left
    in place since asyncpg's DSN-string parser (unlike its connect() kwargs)
    understands it natively."""
    plain = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return _strip(plain, _STRIP_ALWAYS)
