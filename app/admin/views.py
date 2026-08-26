from sqladmin import ModelView

from app.models.orm import (
    AdditiveDetailORM,
    AllergenGroupORM,
    IngredientAliasORM,
    IngredientAllergenORM,
    IngredientORM,
    KbChangeLogORM,
    UnrecognisedTermORM,
    UserORM,
    UserRoleORM,
)


class IngredientAdmin(ModelView, model=IngredientORM):
    name = "Ingredient"
    name_plural = "Ingredients"
    icon = "fa-solid fa-seedling"
    category = "Knowledge base"
    column_list = [IngredientORM.ingredient_id, IngredientORM.canonical_name, IngredientORM.ingredient_type, IngredientORM.is_active]
    column_searchable_list = [IngredientORM.canonical_name]
    column_sortable_list = [IngredientORM.canonical_name, IngredientORM.ingredient_type]
    form_excluded_columns = [IngredientORM.normalised_name, IngredientORM.created_at, IngredientORM.updated_at]


class IngredientAliasAdmin(ModelView, model=IngredientAliasORM):
    name = "Alias"
    name_plural = "Aliases"
    icon = "fa-solid fa-tags"
    category = "Knowledge base"
    column_list = [IngredientAliasORM.alias_text, IngredientAliasORM.ingredient_id, IngredientAliasORM.language_code, IngredientAliasORM.is_curated]
    column_searchable_list = [IngredientAliasORM.alias_text]
    form_excluded_columns = [IngredientAliasORM.normalised_alias]


class IngredientAllergenAdmin(ModelView, model=IngredientAllergenORM):
    name = "Ingredient <-> Allergen link"
    name_plural = "Ingredient <-> Allergen links"
    icon = "fa-solid fa-triangle-exclamation"
    category = "Knowledge base"
    column_list = [IngredientAllergenORM.ingredient_id, IngredientAllergenORM.allergen_group_id, IngredientAllergenORM.certainty]


class AdditiveDetailAdmin(ModelView, model=AdditiveDetailORM):
    name = "Additive"
    name_plural = "Additives"
    icon = "fa-solid fa-flask"
    category = "Knowledge base"
    column_list = [AdditiveDetailORM.ingredient_id, AdditiveDetailORM.e_number, AdditiveDetailORM.additive_category_id, AdditiveDetailORM.concern_level]


class AllergenGroupAdmin(ModelView, model=AllergenGroupORM):
    name = "Allergen group"
    name_plural = "Allergen groups"
    icon = "fa-solid fa-list"
    category = "Knowledge base"
    column_list = [AllergenGroupORM.code, AllergenGroupORM.is_major, AllergenGroupORM.display_order, AllergenGroupORM.is_active]
    can_create = False  # the 9 major groups + sensitivities are a fixed vocabulary, seeded once


class UnrecognisedTermAdmin(ModelView, model=UnrecognisedTermORM):
    """The knowledge-base growth loop the schema was built around (see
    sql/00_schema.sql SECTION 5.10): every ingredient the matcher fails to
    resolve lands here, ranked by frequency, for an admin to map or ignore."""

    name = "Unrecognised term"
    name_plural = "Review queue"
    icon = "fa-solid fa-magnifying-glass"
    category = "Knowledge base"
    column_list = [
        UnrecognisedTermORM.sample_raw_text,
        UnrecognisedTermORM.occurrence_count,
        UnrecognisedTermORM.status,
        UnrecognisedTermORM.last_seen_at,
    ]
    column_default_sort = [(UnrecognisedTermORM.occurrence_count, True)]
    can_create = False


class UserAdmin(ModelView, model=UserORM):
    name = "User"
    name_plural = "Users"
    icon = "fa-solid fa-user"
    category = "Accounts"
    column_list = [UserORM.email, UserORM.display_name, UserORM.is_active, UserORM.email_verified_at, UserORM.created_at]
    column_searchable_list = [UserORM.email, UserORM.display_name]
    form_excluded_columns = [UserORM.password_hash]  # never editable through the admin UI
    can_create = False  # accounts are created through /auth/register only
    can_delete = False  # deactivate (is_active=false) instead of deleting — preserves scan/audit history


class UserRoleAdmin(ModelView, model=UserRoleORM):
    name = "Role grant"
    name_plural = "Role grants"
    icon = "fa-solid fa-user-shield"
    category = "Accounts"
    column_list = [UserRoleORM.user_id, UserRoleORM.role_id, UserRoleORM.granted_at]


class KbChangeLogAdmin(ModelView, model=KbChangeLogORM):
    name = "Change log entry"
    name_plural = "Audit log"
    icon = "fa-solid fa-clock-rotate-left"
    category = "Audit"
    column_list = [KbChangeLogORM.changed_at, KbChangeLogORM.table_name, KbChangeLogORM.operation, KbChangeLogORM.record_id, KbChangeLogORM.changed_by]
    column_default_sort = [(KbChangeLogORM.changed_at, True)]
    can_create = False
    can_edit = False
    can_delete = False  # audit trail — must stay append-only even from the admin panel


ALL_VIEWS = [
    UnrecognisedTermAdmin,
    IngredientAdmin,
    IngredientAliasAdmin,
    IngredientAllergenAdmin,
    AdditiveDetailAdmin,
    AllergenGroupAdmin,
    UserAdmin,
    UserRoleAdmin,
    KbChangeLogAdmin,
]
