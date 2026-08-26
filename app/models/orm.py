"""SQLAdmin needs SQLAlchemy-mapped classes (it inspects a mapper, not a bare
Core Table). Rather than defining columns twice, each class below maps
directly onto the Table objects already declared in kb.py / domain.py /
audit.py via `__table__ = ...` — those Table definitions stay the single
source of truth; this module only adds the ORM layer SQLAdmin requires, for
exactly the tables exposed in the admin panel."""

from sqlalchemy.orm import DeclarativeBase

from app.models import audit as audit_tables
from app.models import domain as domain_tables
from app.models import kb as kb_tables


class Base(DeclarativeBase):
    pass


class IngredientORM(Base):
    __table__ = kb_tables.ingredients


class IngredientAliasORM(Base):
    __table__ = kb_tables.ingredient_aliases


class IngredientAllergenORM(Base):
    __table__ = kb_tables.ingredient_allergens


class AdditiveDetailORM(Base):
    __table__ = kb_tables.additive_details


class UnrecognisedTermORM(Base):
    __table__ = kb_tables.unrecognised_terms


class AllergenGroupORM(Base):
    __table__ = kb_tables.allergen_groups


class UserORM(Base):
    __table__ = domain_tables.users


class UserRoleORM(Base):
    __table__ = domain_tables.user_roles


class KbChangeLogORM(Base):
    __table__ = audit_tables.kb_change_log
